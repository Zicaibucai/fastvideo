"""图片生成适配器：能力声明式（OpenAI 兼容 + Mock）。

提供能力声明 capabilities，前端据此禁用不支持的 Provider 操作。
Mock 使用 Pillow 生成真实可访问的图片文件，不返回不存在的 URL。
"""

from __future__ import annotations

import base64
import time
from typing import Any

from app.adapters.base import BaseAIAdapter, MockMixin
from app.core.exceptions import AIProviderError
from app.core.logging import get_logger
from app.services.image_utils import mock_render_image

logger = get_logger(__name__)

# 能力枚举
CAP_TEXT_TO_IMAGE = "text_to_image"
CAP_IMAGE_TO_IMAGE = "image_to_image"
CAP_INPAINT = "inpaint"
CAP_OUTPAINT = "outpaint"
CAP_UPSCALE = "upscale"
CAP_SEED = "seed"
CAP_MULTIPLE_VARIANTS = "multiple_variants"
CAP_REFERENCE_IMAGE = "reference_image"
CAP_MASK_IMAGE = "mask_image"


class CapabilityError(AIProviderError):
    """Provider 不支持某能力。"""

    code = "CAPABILITY_NOT_SUPPORTED"


class ImageAdapter(BaseAIAdapter):
    provider = "openai"

    CAPABILITIES = {
        CAP_TEXT_TO_IMAGE,
        CAP_SEED,
        CAP_MULTIPLE_VARIANTS,
    }

    def capabilities(self) -> dict[str, bool]:
        return {cap: cap in self.CAPABILITIES for cap in _ALL_CAPS}

    def supports(self, cap: str) -> bool:
        return cap in self.CAPABILITIES

    def is_available(self) -> bool:
        return bool(self.config.get("api_key"))

    def _client(self):
        from openai import OpenAI

        return OpenAI(
            api_key=self.config.get("api_key"),
            base_url=self.config.get("base_url") or None,
            timeout=self.config.get("timeout", 120),
        )

    def _require_capability(self, cap: str) -> None:
        if not self.supports(cap):
            raise CapabilityError(
                f"Provider {self.provider} 不支持 {cap} 操作，不能降级为文生图或生成无关图片。"
            )

    def generate(self, prompt: str, *, size: str | None = None, n: int = 1, **kwargs: Any) -> list[bytes]:
        """文生图：返回 n 张图片二进制列表。"""
        if not self.is_available():
            self._raise_unavailable("text_to_image")
        self._require_capability(CAP_TEXT_TO_IMAGE)
        client = self._client()
        try:
            resp = client.images.generate(
                model=self.config.get("model", "dall-e-3"),
                prompt=prompt,
                size=size or self.config.get("size", "1792x1024"),
                n=n,
                **kwargs,
            )
            images = []
            for item in resp.data:
                if item.b64_json:
                    images.append(base64.b64decode(item.b64_json))
                elif item.url:
                    import httpx

                    r = httpx.get(item.url, timeout=120)
                    r.raise_for_status()
                    images.append(r.content)
                else:
                    raise AIProviderError("图片生成响应为空")
            return images
        except AIProviderError:
            raise
        except Exception as exc:
            logger.exception("image_generate_error")
            raise AIProviderError(f"图片生成失败: {exc}") from exc

    def render_image(
        self,
        source_bytes: bytes | None,
        prompt: str,
        *,
        negative_prompt: str | None = None,
        size: str | None = None,
        n: int = 1,
        seed: int | None = None,
        **kwargs: Any,
    ) -> list[bytes]:
        """图生图渲染。需要 image_to_image 能力。"""
        if not self.is_available():
            self._raise_unavailable("render_image")
        self._require_capability(CAP_IMAGE_TO_IMAGE)
        raise CapabilityError(
            f"Provider {self.provider} 未实现 render_image 接口，请使用 Mock 或接入真实图生图服务。"
        )

    def inpaint_image(
        self,
        source_bytes: bytes,
        mask_bytes: bytes,
        prompt: str,
        *,
        n: int = 1,
        seed: int | None = None,
        **kwargs: Any,
    ) -> list[bytes]:
        """局部重绘。需要 inpaint + mask_image 能力。"""
        if not self.is_available():
            self._raise_unavailable("inpaint")
        self._require_capability(CAP_INPAINT)
        raise CapabilityError(f"Provider {self.provider} 未实现 inpaint_image 接口。")

    def outpaint_image(
        self,
        source_bytes: bytes,
        prompt: str,
        *,
        target_size: str | None = None,
        n: int = 1,
        seed: int | None = None,
        **kwargs: Any,
    ) -> list[bytes]:
        """扩图。需要 outpaint 能力。"""
        if not self.is_available():
            self._raise_unavailable("outpaint")
        self._require_capability(CAP_OUTPAINT)
        raise CapabilityError(f"Provider {self.provider} 未实现 outpaint_image 接口。")

    def upscale_image(self, source_bytes: bytes, *, scale: int = 2, **kwargs: Any) -> list[bytes]:
        """清晰度增强。需要 upscale 能力。"""
        if not self.is_available():
            self._raise_unavailable("upscale")
        self._require_capability(CAP_UPSCALE)
        raise CapabilityError(f"Provider {self.provider} 未实现 upscale_image 接口。")

    def get_task_status(self, task_id: str) -> dict:
        raise CapabilityError(f"Provider {self.provider} 不支持异步任务查询。")

    def cancel_task(self, task_id: str) -> None:
        raise CapabilityError(f"Provider {self.provider} 不支持任务取消。")


class MiniMaxImageAdapter(ImageAdapter):
    """MiniMax ``image-01`` 图片生成 / 参考图渲染适配器。

    MiniMax 当前公开的图生图能力是 ``subject_reference``，并不是带结构约束的
    建筑模型重建。因此这里只声明 reference_image/image_to_image，不虚构局部重绘、
    扩图或超分能力；结构一致性仍由平台的辅助检查和人工复核把关。
    """

    provider = "minimax"
    CAPABILITIES = {
        CAP_TEXT_TO_IMAGE,
        CAP_IMAGE_TO_IMAGE,
        CAP_SEED,
        CAP_MULTIPLE_VARIANTS,
        CAP_REFERENCE_IMAGE,
    }

    def _request_json(self, payload: dict[str, Any]) -> dict[str, Any]:
        import httpx

        base_url = str(self.config.get("base_url") or "https://api.minimaxi.com").rstrip("/")
        try:
            with httpx.Client(timeout=self.config.get("timeout", 180)) as client:
                response = client.post(
                    f"{base_url}/v1/image_generation",
                    headers={
                        "Authorization": f"Bearer {self.config.get('api_key')}",
                        "Content-Type": "application/json",
                    },
                    json=payload,
                )
                response.raise_for_status()
                data = response.json()
        except Exception as exc:
            logger.exception("minimax_image_request_error")
            raise AIProviderError(f"MiniMax 图片请求失败: {exc}") from exc

        base_resp = data.get("base_resp") or {}
        status_code = base_resp.get("status_code", 0)
        if status_code not in (0, None):
            message = base_resp.get("status_msg") or "未知错误"
            raise AIProviderError(f"MiniMax 图片生成失败（{status_code}）: {message}")
        return data

    def _download_image(self, url: str) -> bytes:
        import httpx

        try:
            response = httpx.get(url, timeout=self.config.get("timeout", 180), follow_redirects=True)
            response.raise_for_status()
            return response.content
        except Exception as exc:
            raise AIProviderError(f"MiniMax 图片下载失败: {exc}") from exc

    def _build_prompt(self, prompt: str, negative_prompt: str | None = None) -> str:
        combined = prompt.strip()
        if negative_prompt:
            combined = f"{combined}\n避免出现：{negative_prompt.strip()}"
        # MiniMax image-01 的 prompt 上限为 1500 字符。
        return combined[:1500]

    def _extract_images(self, response: dict[str, Any]) -> list[bytes]:
        data = response.get("data") or {}
        encoded = data.get("image_base64") or []
        urls = data.get("image_urls") or []
        images: list[bytes] = []
        try:
            for item in encoded:
                value = item.split(",", 1)[-1] if isinstance(item, str) else item
                images.append(_normalize_png(base64.b64decode(value)))
            for url in urls:
                images.append(_normalize_png(self._download_image(str(url))))
        except Exception as exc:
            if isinstance(exc, AIProviderError):
                raise
            raise AIProviderError(f"MiniMax 图片响应解析失败: {exc}") from exc
        if not images:
            raise AIProviderError("MiniMax 图片响应中没有可用图片")
        return images

    def generate(
        self,
        prompt: str,
        *,
        size: str | None = None,
        n: int = 1,
        **kwargs: Any,
    ) -> list[bytes]:
        if not self.is_available():
            self._raise_unavailable("text_to_image")
        payload: dict[str, Any] = {
            "model": self.config.get("model", "image-01"),
            "prompt": self._build_prompt(prompt),
            "aspect_ratio": kwargs.pop("aspect_ratio", None) or _size_to_ratio(size),
            "response_format": "base64",
            "n": max(1, min(int(n), 9)),
            "prompt_optimizer": kwargs.pop("prompt_optimizer", True),
        }
        seed = kwargs.pop("seed", None)
        if seed is not None:
            payload["seed"] = int(seed)
        return self._extract_images(self._request_json(payload))

    def render_image(
        self,
        source_bytes: bytes | None,
        prompt: str,
        *,
        negative_prompt: str | None = None,
        size: str | None = None,
        n: int = 1,
        seed: int | None = None,
        **kwargs: Any,
    ) -> list[bytes]:
        if not self.is_available():
            self._raise_unavailable("render_image")
        if not source_bytes:
            raise AIProviderError("MiniMax 参考图渲染必须提供源图片")
        self._require_capability(CAP_IMAGE_TO_IMAGE)
        payload: dict[str, Any] = {
            "model": self.config.get("model", "image-01"),
            "prompt": self._build_prompt(prompt, negative_prompt),
            "subject_reference": [
                {
                    "type": "character",
                    "image_file": _image_data_url(source_bytes),
                }
            ],
            "aspect_ratio": kwargs.pop("aspect_ratio", None) or _size_to_ratio(size),
            "response_format": "base64",
            "n": max(1, min(int(n), 9)),
            "prompt_optimizer": kwargs.pop("prompt_optimizer", True),
        }
        if seed is not None:
            payload["seed"] = int(seed)
        return self._extract_images(self._request_json(payload))


# Mock 适配器：使用 Pillow 生成真实可访问图片
class SeedreamImageAdapter(ImageAdapter):
    """Seedream（火山方舟 Ark）图生图 / 文生图适配器。

    契约（官方 `POST /api/v3/images/generations`）：
    - 图生图通过 ``image`` 参数传入参考图（URL 或 base64 Data URL，可单张或多张数组）。
    - 模型名、基础地址可配置；默认模型 ``doubao-seedream-4-5-251128``。
    - 响应取 ``data[].b64_json``（response_format=b64_json）或 ``data[].url``。
    """

    provider = "seedream"
    CAPABILITIES = {
        CAP_TEXT_TO_IMAGE,
        CAP_IMAGE_TO_IMAGE,
        CAP_REFERENCE_IMAGE,
        CAP_MULTIPLE_VARIANTS,
        CAP_SEED,
    }

    def _request_json(self, payload: dict[str, Any]) -> dict[str, Any]:
        import httpx

        base_url = str(self.config.get("base_url") or "https://ark.cn-beijing.volces.com/api/v3").rstrip("/")
        try:
            with httpx.Client(timeout=self.config.get("timeout", 180)) as client:
                response = client.post(
                    f"{base_url}/images/generations",
                    headers={
                        "Authorization": f"Bearer {self.config.get('api_key')}",
                        "Content-Type": "application/json",
                    },
                    json=payload,
                )
                response.raise_for_status()
                return response.json()
        except httpx.HTTPStatusError as exc:
            message = _extract_ark_error(exc.response.text, exc.response.status_code)
            logger.warning("seedream_image_http_error", status=exc.response.status_code)
            raise AIProviderError(message) from exc
        except AIProviderError:
            raise
        except Exception as exc:
            logger.exception("seedream_image_request_error")
            raise AIProviderError(f"Seedream 图片请求失败: {exc}") from exc

    def _download_image(self, url: str) -> bytes:
        import httpx

        try:
            response = httpx.get(url, timeout=self.config.get("timeout", 180), follow_redirects=True)
            response.raise_for_status()
            return response.content
        except Exception as exc:
            raise AIProviderError(f"Seedream 图片下载失败: {exc}") from exc

    def _extract_images(self, response: dict[str, Any]) -> list[bytes]:
        # Ark 错误也可能以 200 + error 字段返回
        error = response.get("error")
        if isinstance(error, dict) and error.get("message"):
            raise AIProviderError(f"Seedream 图片生成失败: {error.get('message')}")
        images: list[bytes] = []
        try:
            for item in response.get("data") or []:
                if item.get("b64_json"):
                    images.append(_normalize_png(base64.b64decode(item["b64_json"])))
                elif item.get("url"):
                    images.append(_normalize_png(self._download_image(str(item["url"]))))
        except Exception as exc:
            if isinstance(exc, AIProviderError):
                raise
            raise AIProviderError(f"Seedream 图片响应解析失败: {exc}") from exc
        if not images:
            raise AIProviderError("Seedream 图片响应中没有可用图片")
        return images

    def _size_or_ratio(self, size: str | None) -> str:
        """Seedream 4.5 接受 2K/4K 或像素值；平台默认 1792x1024 转为 2K。"""
        s = str(size or self.config.get("size") or "2K").upper()
        if s in ("2K", "4K", "1K", "3K"):
            return s
        return "2K"

    def generate(
        self,
        prompt: str,
        *,
        size: str | None = None,
        n: int = 1,
        **kwargs: Any,
    ) -> list[bytes]:
        if not self.is_available():
            self._raise_unavailable("text_to_image")
        payload: dict[str, Any] = {
            "model": str(self.config.get("model") or "doubao-seedream-4-5-251128"),
            "prompt": (prompt or "")[:2000],
            "size": self._size_or_ratio(size),
            "response_format": "b64_json",
            "watermark": False,
        }
        return self._extract_images(self._request_json(payload))

    def render_image(
        self,
        source_bytes: bytes | None,
        prompt: str,
        *,
        negative_prompt: str | None = None,
        size: str | None = None,
        n: int = 1,
        seed: int | None = None,
        **kwargs: Any,
    ) -> list[bytes]:
        if not self.is_available():
            self._raise_unavailable("render_image")
        if not source_bytes:
            raise AIProviderError("Seedream 图生图必须提供源图片")
        self._require_capability(CAP_IMAGE_TO_IMAGE)
        # Seedream 4.5 不支持独立 negative_prompt 字段，负向约束并入正向提示词。
        combined = (prompt or "").strip()
        if negative_prompt:
            combined = f"{combined}\n避免出现：{negative_prompt.strip()}"
        payload: dict[str, Any] = {
            "model": str(self.config.get("model") or "doubao-seedream-4-5-251128"),
            "prompt": combined[:2000],
            "image": _image_data_url(source_bytes),
            "size": self._size_or_ratio(size),
            "response_format": "b64_json",
            "watermark": False,
        }
        if seed is not None:
            payload["seed"] = int(seed)
        return self._extract_images(self._request_json(payload))


def _extract_ark_error(body: str, status_code: int) -> str:
    """从火山方舟错误响应中提取可读错误信息。"""
    import json

    try:
        parsed = json.loads(body) if body else {}
    except Exception:
        return f"Seedream 图片请求失败（HTTP {status_code}）: {body[:500]}"
    error = parsed.get("error") if isinstance(parsed, dict) else None
    if isinstance(error, dict):
        message = error.get("message") or error.get("code") or "未知错误"
        return f"Seedream 图片生成失败（{status_code}）: {message}"
    if isinstance(parsed, dict) and parsed.get("message"):
        return f"Seedream 图片生成失败（{status_code}）: {parsed['message']}"
    return f"Seedream 图片请求失败（HTTP {status_code}）"


# Mock 适配器：使用 Pillow 生成真实可访问图片
class MockImageAdapter(ImageAdapter, MockMixin):
    provider = "mock"

    CAPABILITIES = {
        CAP_TEXT_TO_IMAGE,
        CAP_IMAGE_TO_IMAGE,
        CAP_INPAINT,
        CAP_OUTPAINT,
        CAP_UPSCALE,
        CAP_SEED,
        CAP_MULTIPLE_VARIANTS,
        CAP_REFERENCE_IMAGE,
        CAP_MASK_IMAGE,
    }

    def is_available(self) -> bool:
        return True

    def _style_from_prompt(self, prompt: str) -> str:
        """从提示词猜测风格。"""
        for style in ("科技蓝", "夜景", "日景", "白模", "绿色", "写实"):
            if style in prompt:
                return style
        return "科技蓝"

    def generate(self, prompt: str, *, size: str | None = None, n: int = 1, **kwargs: Any) -> list[bytes]:
        time.sleep(0.3)
        width, height = _parse_size(size or "1792x1024")
        return [mock_render_image(
            _make_placeholder(width, height), style=self._style_from_prompt(prompt)
        )[0] for _ in range(n)]

    def render_image(
        self,
        source_bytes: bytes | None,
        prompt: str,
        *,
        negative_prompt: str | None = None,
        size: str | None = None,
        n: int = 1,
        seed: int | None = None,
        **kwargs: Any,
    ) -> list[bytes]:
        time.sleep(0.5)
        src = source_bytes or _make_placeholder(1280, 720)
        results = []
        for i in range(n):
            s = seed if seed is not None else (i * 31)
            data, _ = mock_render_image(
                src, style=self._style_from_prompt(prompt), seed=s, operation="render"
            )
            results.append(data)
        return results

    def inpaint_image(
        self,
        source_bytes: bytes,
        mask_bytes: bytes,
        prompt: str,
        *,
        n: int = 1,
        seed: int | None = None,
        **kwargs: Any,
    ) -> list[bytes]:
        time.sleep(0.5)
        results = []
        for i in range(n):
            s = seed if seed is not None else (i * 17)
            data, _ = mock_render_image(
                source_bytes,
                style=self._style_from_prompt(prompt),
                seed=s,
                operation="inpaint",
                mask_bytes=mask_bytes,
            )
            results.append(data)
        return results

    def outpaint_image(
        self,
        source_bytes: bytes,
        prompt: str,
        *,
        target_size: str | None = None,
        n: int = 1,
        seed: int | None = None,
        **kwargs: Any,
    ) -> list[bytes]:
        time.sleep(0.5)
        width, height = _parse_size(target_size or "1920x1080")
        results = []
        for i in range(n):
            s = seed if seed is not None else (i * 7)
            data, _ = mock_render_image(
                source_bytes,
                style=self._style_from_prompt(prompt),
                seed=s,
                operation="outpaint",
                output_width=width,
                output_height=height,
            )
            results.append(data)
        return results

    def upscale_image(self, source_bytes: bytes, *, scale: int = 2, **kwargs: Any) -> list[bytes]:
        time.sleep(0.4)
        data, _ = mock_render_image(source_bytes, seed=42, operation="upscale")
        return [data]

    def get_task_status(self, task_id: str) -> dict:
        return {"status": "success"}

    def cancel_task(self, task_id: str) -> None:
        return None


def _parse_size(size: str) -> tuple[int, int]:
    try:
        w, h = (int(p) for p in size.lower().split("x"))
        return max(w, 100), max(h, 100)
    except Exception:
        return 1792, 1024


def _make_placeholder(width: int, height: int) -> bytes:
    """文生图无源图时的占位底图。"""
    from PIL import Image

    img = Image.new("RGB", (width, height), (30, 58, 95))
    return _img_to_png(img)


def _img_to_png(img) -> bytes:
    import io

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _normalize_png(data: bytes) -> bytes:
    """将 Provider 返回的 JPEG/PNG/WEBP 统一为真实 PNG，匹配存储扩展名。"""
    import io

    from PIL import Image

    with Image.open(io.BytesIO(data)) as image:
        normalized = image.convert("RGBA" if "A" in image.getbands() else "RGB")
        return _img_to_png(normalized)


def _image_data_url(data: bytes) -> str:
    import io

    from PIL import Image

    try:
        with Image.open(io.BytesIO(data)) as image:
            fmt = (image.format or "PNG").lower()
    except Exception as exc:
        raise AIProviderError(f"源图片格式无法识别: {exc}") from exc
    mime = "image/jpeg" if fmt in ("jpg", "jpeg") else f"image/{fmt}"
    return f"data:{mime};base64,{base64.b64encode(data).decode('ascii')}"


def _size_to_ratio(size: str | None) -> str:
    """把平台宽高映射到 MiniMax 支持的最接近画幅。"""
    width, height = _parse_size(size or "1792x1024")
    ratio = width / max(height, 1)
    candidates = {
        "21:9": 21 / 9,
        "16:9": 16 / 9,
        "3:2": 3 / 2,
        "4:3": 4 / 3,
        "1:1": 1.0,
        "3:4": 3 / 4,
        "2:3": 2 / 3,
        "9:16": 9 / 16,
    }
    return min(candidates, key=lambda key: abs(candidates[key] - ratio))


_ALL_CAPS = [
    CAP_TEXT_TO_IMAGE,
    CAP_IMAGE_TO_IMAGE,
    CAP_INPAINT,
    CAP_OUTPAINT,
    CAP_UPSCALE,
    CAP_SEED,
    CAP_MULTIPLE_VARIANTS,
    CAP_REFERENCE_IMAGE,
    CAP_MASK_IMAGE,
]
