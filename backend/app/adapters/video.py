"""视频生成适配器：MiniMax Hailuo + Mock。

说明：OpenAI 图片生成接口（images）并不支持视频，这里为"视频生成"预留统一的
Adapter 接口。真实场景可对接 Runway / Pika / Kling 等视频模型，只需实现 generate
方法并返回视频字节。Mock 实现生成一段 FFmpeg 测试视频。
"""

from __future__ import annotations

import base64
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any

from app.adapters.base import BaseAIAdapter, MockMixin
from app.core.config import settings
from app.core.exceptions import AIProviderError
from app.core.logging import get_logger

logger = get_logger(__name__)


class VideoAdapter(BaseAIAdapter):
    provider = "openai"

    def is_available(self) -> bool:
        # 真实视频生成服务（如 Kling / Runway）接入后在此判断
        return bool(self.config.get("api_key"))

    def generate(self, prompt: str, *, duration: float = 5.0, **kwargs: Any) -> bytes:
        """返回生成的视频二进制数据（MP4）。"""
        if not self.is_available():
            self._raise_unavailable("generate_video")
        # TODO: 对接具体视频生成服务
        raise AIProviderError(
            "当前未配置可用的视频生成服务（如 Kling / Runway / Pika）。"
            "请实现 VideoAdapter.generate 或使用 Mock 演示模式。"
        )

    def capabilities(self) -> dict[str, bool]:
        return {
            "text_to_video": False,
            "image_to_video": False,
            "async_task": False,
            "cancel_task": False,
        }


class MiniMaxVideoAdapter(VideoAdapter):
    """MiniMax Hailuo 视频生成适配器。

    对外保持平台同步 ``generate -> bytes`` 契约，内部按 MiniMax 官方异步流程执行：
    创建任务 → 轮询状态 → 获取 file_id → 下载 MP4。分镜已有画面时自动走图生视频。
    """

    provider = "minimax"

    def capabilities(self) -> dict[str, bool]:
        return {
            "text_to_video": True,
            "image_to_video": True,
            "async_task": True,
            "cancel_task": False,
            "first_last_frame_video": False,  # Hailuo 不支持首尾帧
            "generate_audio": False,
        }

    def _request_json(
        self,
        method: str,
        path: str,
        *,
        payload: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        import httpx

        base_url = str(self.config.get("base_url") or "https://api.minimaxi.com").rstrip("/")
        try:
            with httpx.Client(timeout=self.config.get("timeout", 180)) as client:
                response = client.request(
                    method,
                    f"{base_url}{path}",
                    headers={
                        "Authorization": f"Bearer {self.config.get('api_key')}",
                        "Content-Type": "application/json",
                    },
                    json=payload,
                    params=params,
                )
                response.raise_for_status()
                data = response.json()
        except Exception as exc:
            logger.exception("minimax_video_request_error", path=path)
            raise AIProviderError(f"MiniMax 视频请求失败: {exc}") from exc

        base_resp = data.get("base_resp") or {}
        status_code = base_resp.get("status_code", 0)
        if status_code not in (0, None):
            message = base_resp.get("status_msg") or "未知错误"
            raise AIProviderError(f"MiniMax 视频任务失败（{status_code}）: {message}")
        return data

    def _download_video(self, url: str) -> bytes:
        import httpx

        try:
            response = httpx.get(
                url,
                timeout=self.config.get("video_timeout", 900),
                follow_redirects=True,
            )
            response.raise_for_status()
            if not response.content:
                raise AIProviderError("MiniMax 视频下载内容为空")
            return response.content
        except AIProviderError:
            raise
        except Exception as exc:
            raise AIProviderError(f"MiniMax 视频下载失败: {exc}") from exc

    def get_task_status(self, task_id: str) -> dict[str, Any]:
        return self._request_json(
            "GET",
            "/v1/query/video_generation",
            params={"task_id": task_id},
        )

    def generate(
        self,
        prompt: str,
        *,
        duration: float = 5.0,
        first_frame_bytes: bytes | None = None,
        first_frame_image: str | None = None,
        **kwargs: Any,
    ) -> bytes:
        if not self.is_available():
            self._raise_unavailable("generate_video")

        first_frame = first_frame_image
        if first_frame_bytes:
            first_frame = _video_image_data_url(first_frame_bytes)

        resolution = str(
            kwargs.pop("resolution", None)
            or self.config.get("resolution", "1080P")
        ).upper()
        configured_model = str(self.config.get("model") or "MiniMax-Hailuo-2.3-Fast")
        # Fast 模型仅用于图生视频；没有首帧时切换到文本视频模型。
        model = configured_model
        if not first_frame and configured_model.endswith("-Fast"):
            model = str(self.config.get("text_model") or "MiniMax-Hailuo-2.3")

        normalized_duration = _minimax_duration(duration, resolution)
        payload: dict[str, Any] = {
            "model": model,
            "prompt": (prompt or "建筑工程演示视频")[:2000],
            "duration": normalized_duration,
            "resolution": resolution,
            "prompt_optimizer": bool(kwargs.pop("prompt_optimizer", True)),
        }
        if first_frame:
            payload["first_frame_image"] = first_frame

        created = self._request_json("POST", "/v1/video_generation", payload=payload)
        task_id = created.get("task_id")
        if not task_id:
            raise AIProviderError("MiniMax 创建视频任务后未返回 task_id")

        poll_interval = max(float(self.config.get("poll_interval", 10.0)), 0.0)
        deadline = time.monotonic() + max(float(self.config.get("video_timeout", 900)), 1.0)
        file_id: str | None = None
        while time.monotonic() < deadline:
            result = self.get_task_status(str(task_id))
            status = str(result.get("status") or "").lower()
            if status == "success":
                file_id = result.get("file_id")
                break
            if status in ("fail", "failed"):
                raise AIProviderError(
                    f"MiniMax 视频任务失败: {result.get('error_message') or result.get('message') or '未知错误'}"
                )
            time.sleep(poll_interval)
        if not file_id:
            raise AIProviderError(f"MiniMax 视频生成超时（task_id={task_id}）")

        file_info = self._request_json(
            "GET",
            "/v1/files/retrieve",
            params={"file_id": file_id},
        )
        download_url = (file_info.get("file") or {}).get("download_url")
        if not download_url:
            raise AIProviderError("MiniMax 文件查询未返回 download_url")
        return self._download_video(str(download_url))


class MiniMaxH3VideoAdapter(VideoAdapter):
    """MiniMax H3（Hailuo-03）视频生成适配器 —— V2 接口。

    契约（platform.minimaxi.com V2）：
    - 创建任务 ``POST /v2/video_generation``，body 为多模态 content 数组
      ``[{type:text}, {type:image_url, role:first_frame|last_frame}]``；
    - 查询任务 ``GET /v2/query/video_generation/{task_id}``，状态
      queued/running/succeeded/failed/cancelled，结果取 ``task.content.url``；
    - 模型固定 ``MiniMax-H3``；分辨率 ``768P``/``2K``；时长整数 4~15 秒；
    - 图生视频支持首帧、首尾帧（顺序固定 [first_frame, last_frame]）。

    与旧 V1 ``MiniMaxVideoAdapter``（Hailuo 2.3）并存，V1 代码保留但不再默认使用。
    """

    provider = "minimax"

    def capabilities(self) -> dict[str, bool]:
        return {
            "text_to_video": False,  # 本期页面不开放文生视频（产品规则）
            "image_to_video": True,
            "first_last_frame_video": True,  # H3 V2 原生支持首尾帧
            "async_task": True,
            "cancel_task": False,  # V2 未提供取消接口
            "generate_audio": False,  # V2 无显式声音开关参数
        }

    def _request_json(
        self,
        method: str,
        path: str,
        *,
        payload: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        import httpx

        base_url = str(self.config.get("base_url") or "https://api.minimaxi.com").rstrip("/")
        try:
            with httpx.Client(timeout=self.config.get("timeout", 180)) as client:
                response = client.request(
                    method,
                    f"{base_url}{path}",
                    headers={
                        "Authorization": f"Bearer {self.config.get('api_key')}",
                        "Content-Type": "application/json",
                    },
                    json=payload,
                    params=params,
                )
                response.raise_for_status()
                return response.json()
        except httpx.HTTPStatusError as exc:
            # V2 错误为 OpenAI 风格：{type: error, error: {message, http_code}}
            message = _extract_minimax_v2_error(exc.response.text, exc.response.status_code)
            logger.warning("minimax_h3_http_error", path=path, status=exc.response.status_code)
            raise AIProviderError(message) from exc
        except AIProviderError:
            raise
        except Exception as exc:
            logger.exception("minimax_h3_request_error", path=path)
            raise AIProviderError(f"MiniMax H3 视频请求失败: {exc}") from exc

    def _download_video(self, url: str) -> bytes:
        import httpx

        try:
            response = httpx.get(
                url,
                timeout=self.config.get("video_timeout", 900),
                follow_redirects=True,
            )
            response.raise_for_status()
            if not response.content:
                raise AIProviderError("MiniMax H3 视频下载内容为空")
            return response.content
        except AIProviderError:
            raise
        except Exception as exc:
            raise AIProviderError(f"MiniMax H3 视频下载失败: {exc}") from exc

    def create_generation_task(
        self,
        *,
        prompt: str,
        first_frame_bytes: bytes | None = None,
        last_frame_bytes: bytes | None = None,
        mode: str = "image_to_video",
        duration: int = 5,
        resolution: str | None = None,
        aspect_ratio: str | None = None,
        seed: int | None = None,
        generate_audio: bool = False,
        watermark: bool = False,
    ) -> str:
        """创建 MiniMax H3 异步视频生成任务，返回 task_id。"""
        if not self.is_available():
            self._raise_unavailable("generate_video")

        content: list[dict[str, Any]] = [
            {"type": "text", "text": (prompt or "建筑工程演示视频")[:7000]}
        ]
        if mode == "image_to_video":
            if not first_frame_bytes:
                raise AIProviderError(
                    "MiniMax H3 图生视频必须提供首帧图片，本期不开放文生视频回退。"
                )
            content.append(
                {
                    "type": "image_url",
                    "image_url": {"url": _video_image_data_url(first_frame_bytes)},
                    "role": "first_frame",
                }
            )
        elif mode == "first_last_frame_video":
            if not first_frame_bytes or not last_frame_bytes:
                raise AIProviderError(
                    "MiniMax H3 首尾帧模式必须同时提供首帧与尾帧两张图片（顺序固定为先首帧后尾帧）。"
                )
            content.append(
                {
                    "type": "image_url",
                    "image_url": {"url": _video_image_data_url(first_frame_bytes)},
                    "role": "first_frame",
                }
            )
            content.append(
                {
                    "type": "image_url",
                    "image_url": {"url": _video_image_data_url(last_frame_bytes)},
                    "role": "last_frame",
                }
            )
        else:
            raise AIProviderError(f"MiniMax H3 不支持的生成模式: {mode}")

        payload: dict[str, Any] = {
            "model": str(self.config.get("model") or "MiniMax-H3"),
            "content": content,
            "resolution": _minimax_h3_resolution(
                resolution or self.config.get("resolution")
            ),
            "duration": _minimax_h3_duration(duration),
            "ratio": str(aspect_ratio or "adaptive"),
            "aigc_watermark": bool(watermark),
        }
        created = self._request_json("POST", "/v2/video_generation", payload=payload)
        task_id = created.get("task_id")
        if not task_id:
            raise AIProviderError("MiniMax H3 创建视频任务后未返回 task_id")
        return str(task_id)

    def get_task_status(self, task_id: str) -> dict[str, Any]:
        """查询任务状态，返回标准化结果（status 小写）。"""
        data = self._request_json("GET", f"/v2/query/video_generation/{task_id}")
        task = data.get("task") or data
        video_url = (task.get("content") or {}).get("url")
        fail_reason = (task.get("error") or {}).get("message") or task.get("fail_reason")
        return {
            "id": task.get("id") or task_id,
            "status": str(task.get("status") or "unknown").lower(),
            "video_url": video_url,
            "fail_reason": fail_reason,
            "raw": data,
        }

    def generate(
        self,
        prompt: str,
        *,
        duration: float = 5.0,
        first_frame_bytes: bytes | None = None,
        last_frame_bytes: bytes | None = None,
        **kwargs: Any,
    ) -> bytes:
        """同步便捷入口：创建任务 → 轮询 → 下载 MP4。必须提供首帧。"""
        mode = kwargs.pop("mode", None) or (
            "first_last_frame_video" if last_frame_bytes else "image_to_video"
        )
        task_id = self.create_generation_task(
            prompt=prompt,
            first_frame_bytes=first_frame_bytes,
            last_frame_bytes=last_frame_bytes,
            mode=mode,
            duration=max(1, int(duration)),
            resolution=kwargs.pop("resolution", None),
            aspect_ratio=kwargs.pop("aspect_ratio", None),
            generate_audio=kwargs.pop("generate_audio", False),
            watermark=kwargs.pop("watermark", False),
        )
        poll_interval = max(float(self.config.get("poll_interval", 10.0)), 0.0)
        deadline = time.monotonic() + max(
            float(self.config.get("video_timeout", 900)), 1.0
        )
        while time.monotonic() < deadline:
            result = self.get_task_status(str(task_id))
            status = str(result.get("status") or "").lower()
            if status == "succeeded":
                video_url = result.get("video_url")
                if not video_url:
                    raise AIProviderError("MiniMax H3 任务成功但未返回视频地址")
                return self._download_video(str(video_url))
            if status in ("failed", "cancelled"):
                raise AIProviderError(
                    f"MiniMax H3 视频任务{status}: {result.get('fail_reason') or '未知错误'}"
                )
            time.sleep(poll_interval)
        raise AIProviderError(f"MiniMax H3 视频生成超时（task_id={task_id}）")


class SeedanceVideoAdapter(VideoAdapter):
    """Seedance（火山方舟 Ark）视频生成适配器。

    采用「图片驱动视频分镜」工作流：
    - 图生视频（image_to_video）：上传 1 张首帧；
    - 首尾帧（first_last_frame_video）：上传 2 张图片，顺序固定为
      [first_frame, last_frame]；
    - 不支持文生视频，text_to_video=False；不提供任何自动回退。

    能力矩阵：image_to_video / first_last_frame_video / async_task / cancel_task。
    模型名、基础地址均来自配置，禁止写死第三方网关地址或模型 ID。
    """

    provider = "seedance"

    def capabilities(self) -> dict[str, bool]:
        return {
            "text_to_video": False,
            "image_to_video": True,
            "first_last_frame_video": True,
            "async_task": True,
            "cancel_task": True,
            "generate_audio": True,  # Seedance 2.0 支持生成同步声音（默认关闭）
        }

    def is_available(self) -> bool:
        return bool(self.config.get("api_key"))

    # ---------------- 内部 HTTP ----------------

    def _request_json(
        self,
        method: str,
        path: str,
        *,
        payload: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        import httpx

        base_url = str(
            self.config.get("base_url") or settings.seedance_base_url
        ).rstrip("/")
        try:
            with httpx.Client(timeout=self.config.get("timeout", 180)) as client:
                response = client.request(
                    method,
                    f"{base_url}{path}",
                    headers={
                        "Authorization": f"Bearer {self.config.get('api_key')}",
                        "Content-Type": "application/json",
                    },
                    json=payload,
                    params=params,
                )
                response.raise_for_status()
                data = response.json()
        except httpx.HTTPStatusError as exc:
            body = exc.response.text
            message = _extract_seedance_error(body, exc.response.status_code)
            logger.warning("seedance_video_http_error", path=path, status=exc.response.status_code)
            raise AIProviderError(message) from exc
        except AIProviderError:
            raise
        except Exception as exc:
            logger.exception("seedance_video_request_error", path=path)
            raise AIProviderError(f"Seedance 视频请求失败: {exc}") from exc

        # Ark 错误也通过 JSON body 返回（{ "error": { "code": ..., "message": ... } }）
        error = data.get("error")
        if isinstance(error, dict) and error.get("message"):
            raise AIProviderError(f"Seedance 视频任务失败: {error.get('message')}")
        return data

    def _download_video(self, url: str) -> bytes:
        import httpx

        try:
            response = httpx.get(
                url,
                timeout=self.config.get("video_timeout", 900),
                follow_redirects=True,
            )
            response.raise_for_status()
            if not response.content:
                raise AIProviderError("Seedance 视频下载内容为空")
            return response.content
        except AIProviderError:
            raise
        except Exception as exc:
            raise AIProviderError(f"Seedance 视频下载失败: {exc}") from exc

    # ---------------- 公开能力 ----------------

    def create_generation_task(
        self,
        *,
        prompt: str,
        first_frame_bytes: bytes | None = None,
        last_frame_bytes: bytes | None = None,
        mode: str = "image_to_video",
        duration: int = 5,
        resolution: str | None = None,
        aspect_ratio: str | None = None,
        seed: int | None = None,
        generate_audio: bool = False,
        watermark: bool = False,
    ) -> str:
        """创建 Seedance 异步视频生成任务，返回任务 ID。

        图片必须显式传入，顺序固定为 [first_frame, last_frame]；
        未提供首帧时直接报错，绝不自动回退文生视频。
        """
        if not self.is_available():
            self._raise_unavailable("generate_video")

        content: list[dict[str, Any]] = [
            {"type": "text", "text": (prompt or "建筑工程演示视频")[:2000]}
        ]

        if mode == "image_to_video":
            if not first_frame_bytes:
                raise AIProviderError(
                    "Seedance 图生视频必须提供首帧图片，本期不开放文生视频回退。"
                )
            content.append(
                {
                    "type": "image_url",
                    "image_url": {"url": _video_image_data_url(first_frame_bytes)},
                    "role": "first_frame",
                }
            )
        elif mode == "first_last_frame_video":
            if not first_frame_bytes or not last_frame_bytes:
                raise AIProviderError(
                    "Seedance 首尾帧模式必须同时提供首帧与尾帧两张图片（顺序固定为先首帧后尾帧）。"
                )
            content.append(
                {
                    "type": "image_url",
                    "image_url": {"url": _video_image_data_url(first_frame_bytes)},
                    "role": "first_frame",
                }
            )
            content.append(
                {
                    "type": "image_url",
                    "image_url": {"url": _video_image_data_url(last_frame_bytes)},
                    "role": "last_frame",
                }
            )
        else:
            raise AIProviderError(f"Seedance 不支持的生成模式: {mode}")

        payload: dict[str, Any] = {
            "model": str(self.config.get("model") or settings.seedance_video_model),
            "content": content,
            "duration": int(duration),
            "resolution": str(
                resolution
                or self.config.get("resolution")
                or settings.seedance_video_resolution
                or "720p"
            ),
            "watermark": bool(watermark),
            # 默认关闭生成声音，避免生成不可控的音效/对白。
            "generate_audio": bool(generate_audio),
        }
        if aspect_ratio:
            payload["ratio"] = str(aspect_ratio)
        if seed is not None:
            payload["seed"] = int(seed)

        created = self._request_json(
            "POST", "/contents/generations/tasks", payload=payload
        )
        task_id = created.get("id") or created.get("task_id")
        if not task_id:
            raise AIProviderError("Seedance 创建视频任务后未返回任务 ID")
        return str(task_id)

    def get_task_status(self, task_id: str) -> dict[str, Any]:
        """查询任务状态，返回标准化结果。

        status 归一化为小写：queued | running | succeeded | failed | expired | cancelled。
        """
        data = self._request_json(
            "GET", f"/contents/generations/tasks/{task_id}"
        )
        content = data.get("content") or data.get("result") or {}
        video_url = content.get("video_url") or data.get("video_url")
        fail_reason = (
            data.get("fail_reason")
            or data.get("error_message")
            or (data.get("error") or {}).get("message")
        )
        return {
            "id": data.get("id") or task_id,
            "status": str(data.get("status") or "unknown").lower(),
            "video_url": video_url,
            "fail_reason": fail_reason,
            "raw": data,
        }

    def cancel_task(self, task_id: str) -> bool:
        """取消 Seedance 任务（DELETE 接口：queued 取消，已完成则删除历史）。"""
        try:
            self._request_json("DELETE", f"/contents/generations/tasks/{task_id}")
            return True
        except AIProviderError:
            logger.warning("seedance_cancel_task_failed", task_id=task_id)
            return False

    def generate(
        self,
        prompt: str,
        *,
        duration: float = 5.0,
        first_frame_bytes: bytes | None = None,
        last_frame_bytes: bytes | None = None,
        **kwargs: Any,
    ) -> bytes:
        """同步便捷入口：创建任务 → 轮询 → 下载 MP4。

        必须提供首帧（图片驱动）；不提供文生视频回退。
        """
        mode = kwargs.pop("mode", None) or (
            "first_last_frame_video" if last_frame_bytes else "image_to_video"
        )
        task_id = self.create_generation_task(
            prompt=prompt,
            first_frame_bytes=first_frame_bytes,
            last_frame_bytes=last_frame_bytes,
            mode=mode,
            duration=max(1, int(duration)),
            resolution=kwargs.pop("resolution", None),
            aspect_ratio=kwargs.pop("aspect_ratio", None),
            seed=kwargs.pop("seed", None),
            generate_audio=kwargs.pop("generate_audio", False),
            watermark=kwargs.pop("watermark", False),
        )

        poll_interval = max(float(self.config.get("poll_interval", 10.0)), 0.0)
        deadline = time.monotonic() + max(
            float(self.config.get("video_timeout", 900)), 1.0
        )
        while time.monotonic() < deadline:
            result = self.get_task_status(str(task_id))
            status = str(result.get("status") or "").lower()
            if status == "succeeded":
                video_url = result.get("video_url")
                if not video_url:
                    raise AIProviderError("Seedance 任务成功但未返回视频地址")
                return self._download_video(str(video_url))
            if status in ("failed", "expired", "cancelled"):
                raise AIProviderError(
                    f"Seedance 视频任务{status}: {result.get('fail_reason') or '未知错误'}"
                )
            time.sleep(poll_interval)
        raise AIProviderError(f"Seedance 视频生成超时（task_id={task_id}）")


class MockVideoAdapter(VideoAdapter, MockMixin):
    """Mock 视频生成：用 FFmpeg 生成一段带文字的测试视频。"""

    provider = "mock"

    def is_available(self) -> bool:
        return True

    def capabilities(self) -> dict[str, bool]:
        return {
            "text_to_video": True,
            "image_to_video": True,
            "first_last_frame_video": True,
            "async_task": False,
            "cancel_task": False,
        }

    def generate(self, prompt: str, *, duration: float = 5.0, **kwargs: Any) -> bytes:
        time.sleep(0.8)  # 模拟耗时
        return generate_test_video(
            text=(prompt or "工程投标视频")[:30],
            duration=duration,
            width=settings.video_width,
            height=settings.video_height,
            fps=settings.video_fps,
        )


def generate_test_video(
    text: str,
    duration: float = 5.0,
    width: int = 1920,
    height: int = 1080,
    fps: int = 30,
    color: str = "0x1e3a5f",
) -> bytes:
    """用 FFmpeg 生成测试视频。需要系统安装 ffmpeg。"""
    safe_text = text.replace(":", "").replace("'", "").replace("\\", "")
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "out.mp4"
        cmd = [
            settings.ffmpeg_binary,
            "-y",
            "-f",
            "lavfi",
            "-i",
            f"color=c={color}:s={width}x{height}:d={duration}:r={fps}",
            "-vf",
            f"drawtext=text='{safe_text}':fontcolor=white:fontsize=48:x=(w-text_w)/2:y=(h-text_h)/2",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            str(out),
        ]
        try:
            subprocess.run(cmd, check=True, capture_output=True, timeout=60)
        except subprocess.CalledProcessError as exc:
            # 部分 FFmpeg 发行包（例如未启用 libfreetype 的 Homebrew
            # 构建）不包含 drawtext。Mock 视频仍应能用于流程验证，
            # 因此在该情况下退化为无文字色块视频。
            stderr = exc.stderr.decode(errors="replace")
            if "No such filter: 'drawtext'" not in stderr and "Filter not found" not in stderr:
                logger.warning("ffmpeg_test_video_failed", stderr=stderr[:500])
                raise AIProviderError(f"FFmpeg 生成测试视频失败: {exc}") from exc

            logger.warning("ffmpeg_drawtext_unavailable_fallback", stderr=stderr[:500])
            fallback_cmd = [
                settings.ffmpeg_binary,
                "-y",
                "-f",
                "lavfi",
                "-i",
                f"color=c={color}:s={width}x{height}:d={duration}:r={fps}",
                "-c:v",
                "libx264",
                "-pix_fmt",
                "yuv420p",
                str(out),
            ]
            try:
                subprocess.run(fallback_cmd, check=True, capture_output=True, timeout=60)
            except subprocess.CalledProcessError as fallback_exc:
                fallback_stderr = fallback_exc.stderr.decode(errors="replace")
                logger.warning("ffmpeg_test_video_fallback_failed", stderr=fallback_stderr[:500])
                raise AIProviderError(f"FFmpeg 生成测试视频失败: {fallback_exc}") from fallback_exc
        except FileNotFoundError:
            raise AIProviderError("未找到 ffmpeg，请安装 FFmpeg 后重试。")
        return out.read_bytes()


def _video_image_data_url(data: bytes) -> str:
    """将首帧转换为 MiniMax 支持的 Base64 Data URL，并先验证图片格式。"""
    import io

    from PIL import Image

    try:
        with Image.open(io.BytesIO(data)) as image:
            fmt = (image.format or "PNG").lower()
    except Exception as exc:
        raise AIProviderError(f"图生视频首帧格式无法识别: {exc}") from exc
    mime = "image/jpeg" if fmt in ("jpg", "jpeg") else f"image/{fmt}"
    return f"data:{mime};base64,{base64.b64encode(data).decode('ascii')}"


def _extract_seedance_error(body: str, status_code: int) -> str:
    """从 Seedance/Ark 错误响应中提取可读错误信息。"""
    import json

    try:
        parsed = json.loads(body) if body else {}
    except Exception:
        return f"Seedance 视频请求失败（HTTP {status_code}）: {body[:500]}"
    error = parsed.get("error") if isinstance(parsed, dict) else None
    if isinstance(error, dict):
        message = error.get("message") or error.get("code") or "未知错误"
        return f"Seedance 视频任务失败（{status_code}）: {message}"
    if isinstance(parsed, dict) and parsed.get("message"):
        return f"Seedance 视频任务失败（{status_code}）: {parsed['message']}"
    return f"Seedance 视频请求失败（HTTP {status_code}）"


def _extract_minimax_v2_error(body: str, status_code: int) -> str:
    """从 MiniMax V2（OpenAI 风格）错误响应中提取可读错误信息。"""
    import json

    try:
        parsed = json.loads(body) if body else {}
    except Exception:
        return f"MiniMax H3 视频请求失败（HTTP {status_code}）: {body[:500]}"
    error = parsed.get("error") if isinstance(parsed, dict) else None
    if isinstance(error, dict) and error.get("message"):
        return f"MiniMax H3 视频任务失败（{status_code}）: {error['message']}"
    return f"MiniMax H3 视频请求失败（HTTP {status_code}）"


def _minimax_h3_resolution(value: str | None) -> str:
    """映射到 H3 支持的 768P / 2K。平台 480p/720p → 768P，1080p/2K → 2K。"""
    v = str(value or "").upper()
    return "2K" if v in ("2K", "1080P") else "768P"


def _minimax_h3_duration(duration: float | int) -> int:
    """H3 时长为整数 4~15 秒。"""
    return max(4, min(int(duration or 5), 15))


def _minimax_duration(duration: float, resolution: str) -> int:
    """映射到 Hailuo 当前支持的 6/10 秒组合；1080P 固定 6 秒。"""
    if resolution.upper() == "1080P":
        return 6
    return 10 if float(duration) >= 8 else 6
