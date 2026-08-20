"""DeepSeek / MiniMax Provider 契约测试（不发起真实付费请求）。"""

from __future__ import annotations

import base64
import io
import os
from types import SimpleNamespace

import pytest
from PIL import Image

# 保证本文件单独运行或先于 API 测试收集时，不会误连本机 Celery/MinIO。
os.environ.setdefault("DATABASE_URL", "sqlite:////tmp/fastvideo_provider_test.db")
os.environ.setdefault("USE_CELERY", "false")
os.environ.setdefault("STORAGE_BACKEND", "local")

from app.adapters.factory import (
    ai_status,
    get_image_adapter,
    get_llm_adapter,
    get_tts_adapter,
    get_video_adapter,
)
from app.adapters.image import MiniMaxImageAdapter, SeedreamImageAdapter
from app.adapters.llm import DeepSeekLLMAdapter
from app.adapters.tts import VolcengineTTSAdapter, VOLCENGINE_VOICES
from app.adapters.video import MiniMaxH3VideoAdapter, MiniMaxVideoAdapter, SeedanceVideoAdapter
from app.core.config import settings


def _png(color=(32, 80, 120)) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (640, 360), color).save(buffer, format="PNG")
    return buffer.getvalue()


def _clear_adapter_caches() -> None:
    get_llm_adapter.cache_clear()
    get_image_adapter.cache_clear()
    get_video_adapter.cache_clear()
    get_tts_adapter.cache_clear()


def test_factory_selects_deepseek_and_minimax(monkeypatch):
    monkeypatch.setattr(settings, "ai_llm_provider", "deepseek")
    monkeypatch.setattr(settings, "ai_llm_model", "deepseek-v4-flash")
    monkeypatch.setattr(settings, "deepseek_api_key", "test-deepseek-key")
    monkeypatch.setattr(settings, "ai_image_provider", "minimax")
    monkeypatch.setattr(settings, "ai_image_model", "image-01")
    monkeypatch.setattr(settings, "ai_video_provider", "minimax")
    monkeypatch.setattr(settings, "ai_video_model", "MiniMax-Hailuo-2.3-Fast")
    monkeypatch.setattr(settings, "minimax_api_key", "test-minimax-key")
    _clear_adapter_caches()

    assert isinstance(get_llm_adapter(), DeepSeekLLMAdapter)
    assert isinstance(get_image_adapter(), MiniMaxImageAdapter)
    assert isinstance(get_video_adapter(), MiniMaxH3VideoAdapter)  # minimax 视频已切换到 H3（V2 接口）
    assert get_llm_adapter().config["model"] == "deepseek-v4-flash"
    assert get_image_adapter().config["model"] == "image-01"

    _clear_adapter_caches()


def test_status_keeps_disabled_tts_separate_from_core_mock_mode(monkeypatch):
    monkeypatch.setattr(settings, "ai_llm_provider", "deepseek")
    monkeypatch.setattr(settings, "deepseek_api_key", "test-deepseek-key")
    monkeypatch.setattr(settings, "ai_image_provider", "minimax")
    monkeypatch.setattr(settings, "minimax_api_key", "test-minimax-key")
    monkeypatch.setattr(settings, "ai_video_provider", "minimax")
    monkeypatch.setattr(settings, "ai_tts_provider", "disabled")
    _clear_adapter_caches()

    status = ai_status()

    assert status["mock_mode"] is False
    assert status["tts_mock_mode"] is True
    _clear_adapter_caches()


def test_deepseek_uses_openai_compatible_chat(monkeypatch):
    captured = {}

    class FakeCompletions:
        def create(self, **kwargs):
            captured["request"] = kwargs
            return SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(content='{"shots": []}'))]
            )

    class FakeOpenAI:
        def __init__(self, **kwargs):
            captured["client"] = kwargs
            self.chat = SimpleNamespace(completions=FakeCompletions())

    monkeypatch.setattr("openai.OpenAI", FakeOpenAI)
    adapter = DeepSeekLLMAdapter(
        api_key="ds-test",
        base_url="https://api.deepseek.com",
        timeout=120,
        model="deepseek-v4-flash",
    )
    result = adapter.chat([{"role": "user", "content": "输出 JSON"}], temperature=0.2)

    assert result == '{"shots": []}'
    assert captured["client"]["base_url"] == "https://api.deepseek.com"
    assert captured["request"]["model"] == "deepseek-v4-flash"
    assert captured["request"]["messages"][0]["content"] == "输出 JSON"


def test_minimax_image_payload_and_capabilities():
    captured: list[dict] = []
    encoded = base64.b64encode(_png()).decode("ascii")

    class FakeMiniMaxImage(MiniMaxImageAdapter):
        def _request_json(self, payload):
            captured.append(payload)
            return {
                "data": {"image_base64": [encoded]},
                "base_resp": {"status_code": 0, "status_msg": "success"},
            }

    adapter = FakeMiniMaxImage(
        api_key="minimax-test",
        base_url="https://api.minimaxi.com",
        model="image-01",
        size="1792x1024",
    )
    generated = adapter.generate("科技蓝建筑鸟瞰", n=1, seed=7)
    rendered = adapter.render_image(
        _png(),
        "建筑写实渲染，保持主体",
        negative_prompt="不得增加楼层",
        n=1,
        seed=8,
    )

    assert Image.open(io.BytesIO(generated[0])).format == "PNG"
    assert Image.open(io.BytesIO(rendered[0])).format == "PNG"
    assert captured[0]["model"] == "image-01"
    assert captured[0]["aspect_ratio"] == "16:9"
    assert captured[0]["response_format"] == "base64"
    assert captured[1]["subject_reference"][0]["image_file"].startswith(
        "data:image/png;base64,"
    )
    assert "不得增加楼层" in captured[1]["prompt"]
    assert adapter.capabilities()["image_to_image"] is True
    assert adapter.capabilities()["inpaint"] is False
    assert adapter.capabilities()["outpaint"] is False
    assert adapter.capabilities()["upscale"] is False


def test_minimax_image_to_video_poll_and_download():
    calls: list[tuple[str, str, dict | None, dict | None]] = []

    class FakeMiniMaxVideo(MiniMaxVideoAdapter):
        def _request_json(self, method, path, *, payload=None, params=None):
            calls.append((method, path, payload, params))
            if path == "/v1/video_generation":
                return {"task_id": "task-1", "base_resp": {"status_code": 0}}
            if path == "/v1/query/video_generation":
                return {"status": "Success", "file_id": "file-1"}
            return {"file": {"download_url": "https://example.invalid/result.mp4"}}

        def _download_video(self, url):
            assert url.endswith("result.mp4")
            return b"fake-mp4"

    adapter = FakeMiniMaxVideo(
        api_key="minimax-test",
        base_url="https://api.minimaxi.com",
        model="MiniMax-Hailuo-2.3-Fast",
        text_model="MiniMax-Hailuo-2.3",
        resolution="1080P",
        poll_interval=0,
        video_timeout=5,
    )
    result = adapter.generate("镜头缓慢推进", duration=12, first_frame_bytes=_png())

    create_payload = calls[0][2]
    assert result == b"fake-mp4"
    assert create_payload is not None
    assert create_payload["model"] == "MiniMax-Hailuo-2.3-Fast"
    assert create_payload["duration"] == 6
    assert create_payload["resolution"] == "1080P"
    assert create_payload["first_frame_image"].startswith("data:image/png;base64,")
    assert calls[1][3] == {"task_id": "task-1"}
    assert calls[2][3] == {"file_id": "file-1"}


def test_minimax_text_video_switches_off_fast_model():
    calls = []

    class FakeMiniMaxVideo(MiniMaxVideoAdapter):
        def _request_json(self, method, path, *, payload=None, params=None):
            calls.append((path, payload))
            if path == "/v1/video_generation":
                return {"task_id": "task-2"}
            if path == "/v1/query/video_generation":
                return {"status": "Success", "file_id": "file-2"}
            return {"file": {"download_url": "https://example.invalid/text.mp4"}}

        def _download_video(self, url):
            return b"text-video"

    adapter = FakeMiniMaxVideo(
        api_key="minimax-test",
        model="MiniMax-Hailuo-2.3-Fast",
        text_model="MiniMax-Hailuo-2.3",
        resolution="1080P",
        poll_interval=0,
        video_timeout=5,
    )
    assert adapter.generate("施工现场航拍") == b"text-video"
    assert calls[0][1]["model"] == "MiniMax-Hailuo-2.3"
    assert "first_frame_image" not in calls[0][1]


# ============================================================
# Seedance（火山方舟 Ark）契约测试
# 注意：以下为 Mock HTTP 契约测试，仅验证请求/响应契约，不发起真实付费请求。
# ============================================================


def _seedance_adapter(**kwargs):
    base = {
        "api_key": "seedance-test",
        "base_url": "https://ark.cn-beijing.volces.com/api/v3",
        "model": "doubao-seedance-1-0-pro-250528",
        "resolution": "720p",
        "poll_interval": 0,
        "video_timeout": 5,
    }
    base.update(kwargs)
    return SeedanceVideoAdapter(**base)


def test_seedance_capabilities():
    adapter = _seedance_adapter()
    caps = adapter.capabilities()
    assert caps["image_to_video"] is True
    assert caps["first_last_frame_video"] is True
    assert caps["text_to_video"] is False
    assert caps["async_task"] is True
    assert caps["cancel_task"] is True


def test_seedance_image_to_video_payload_contract():
    """图生视频：仅 1 张首帧，role=first_frame，默认关闭声音，模型/地址来自配置。"""
    calls: list[dict] = []

    class FakeSeedance(SeedanceVideoAdapter):
        def _request_json(self, method, path, *, payload=None, params=None):
            calls.append({"method": method, "path": path, "payload": payload})
            return {"id": "cgt-task-1"}

    adapter = FakeSeedance(
        api_key="seedance-test",
        base_url="https://ark.cn-beijing.volces.com/api/v3",
        model="doubao-seedance-1-0-pro-250528",
        resolution="720p",
        poll_interval=0,
        video_timeout=5,
    )
    task_id = adapter.create_generation_task(
        prompt="建筑缓慢推进",
        first_frame_bytes=_png(),
        mode="image_to_video",
        duration=5,
        aspect_ratio="adaptive",
        generate_audio=False,
    )

    assert task_id == "cgt-task-1"
    call = calls[0]
    assert call["method"] == "POST"
    assert call["path"] == "/contents/generations/tasks"
    payload = call["payload"]
    assert payload["model"] == "doubao-seedance-1-0-pro-250528"
    assert payload["duration"] == 5
    assert payload["resolution"] == "720p"
    assert payload["ratio"] == "adaptive"
    assert payload["generate_audio"] is False
    assert payload["watermark"] is False
    # content: [text, first_frame]，首帧 role 固定为 first_frame
    assert payload["content"][0] == {"type": "text", "text": "建筑缓慢推进"}
    first = payload["content"][1]
    assert first["type"] == "image_url"
    assert first["role"] == "first_frame"
    assert first["image_url"]["url"].startswith("data:image/png;base64,")
    assert len(payload["content"]) == 2


def test_seedance_first_last_frame_contract_preserves_order():
    """首尾帧：content 顺序固定为 [first_frame, last_frame]，role 正确。"""
    calls: list[dict] = []
    first_png = _png(color=(10, 20, 30))
    last_png = _png(color=(200, 60, 90))

    class FakeSeedance(SeedanceVideoAdapter):
        def _request_json(self, method, path, *, payload=None, params=None):
            calls.append(payload)
            return {"id": "cgt-task-2"}

    adapter = FakeSeedance(
        api_key="seedance-test",
        base_url="https://ark.cn-beijing.volces.com/api/v3",
        model="doubao-seedance-1-0-pro-250528",
        poll_interval=0,
        video_timeout=5,
    )
    task_id = adapter.create_generation_task(
        prompt="白模过渡到写实",
        first_frame_bytes=first_png,
        last_frame_bytes=last_png,
        mode="first_last_frame_video",
        duration=10,
        generate_audio=False,
    )

    assert task_id == "cgt-task-2"
    payload = calls[0]
    roles = [item.get("role") for item in payload["content"][1:]]
    assert roles == ["first_frame", "last_frame"]
    assert len(payload["content"]) == 3  # text + 2 图
    assert payload["content"][1]["image_url"]["url"].endswith(
        base64.b64encode(first_png).decode("ascii")
    )
    assert payload["content"][2]["image_url"]["url"].endswith(
        base64.b64encode(last_png).decode("ascii")
    )
    assert payload["duration"] == 10


def test_seedance_rejects_first_last_without_two_images():
    """首尾帧模式缺一张图必须报错，不允许降级成普通图生视频。"""
    adapter = _seedance_adapter()
    with pytest.raises(Exception) as exc:
        adapter.create_generation_task(
            prompt="缺尾帧",
            first_frame_bytes=_png(),
            last_frame_bytes=None,
            mode="first_last_frame_video",
        )
    assert "首帧与尾帧" in str(exc.value)


def test_seedance_image_to_video_requires_first_frame_no_text_fallback():
    """图生视频未提供首帧直接报错，绝不自动回退文生视频。"""
    adapter = _seedance_adapter()
    with pytest.raises(Exception) as exc:
        adapter.create_generation_task(
            prompt="无图",
            first_frame_bytes=None,
            mode="image_to_video",
        )
    assert "必须提供首帧" in str(exc.value)
    # 同步入口同样拒绝
    with pytest.raises(Exception) as exc2:
        adapter.generate("无图", first_frame_bytes=None)
    assert "必须提供首帧" in str(exc2.value)


def test_seedance_poll_and_download_and_cancel():
    """异步提交→轮询 succeeded→下载；cancel 走 DELETE。"""
    calls: list[tuple[str, str]] = []
    status_states = iter([{"status": "queued"}, {"status": "succeeded", "content": {"video_url": "https://example.invalid/v.mp4"}}])

    class FakeSeedance(SeedanceVideoAdapter):
        def _request_json(self, method, path, *, payload=None, params=None):
            calls.append((method, path))
            if method == "POST":
                return {"id": "cgt-task-3"}
            if method == "GET":
                return next(status_states)
            return {}

        def _download_video(self, url):
            assert url.endswith("v.mp4")
            return b"seedance-mp4"

    adapter = FakeSeedance(
        api_key="seedance-test",
        base_url="https://ark.cn-beijing.volces.com/api/v3",
        poll_interval=0,
        video_timeout=5,
    )
    result = adapter.generate("缓慢推进", duration=5, first_frame_bytes=_png())

    assert result == b"seedance-mp4"
    methods = [c[0] for c in calls]
    assert methods == ["POST", "GET", "GET", "DELETE"] or methods == ["POST", "GET", "GET"]
    # cancel 接口走 DELETE
    adapter.cancel_task("cgt-task-3")
    assert calls[-1] == ("DELETE", "/contents/generations/tasks/cgt-task-3")


def test_seedance_status_parses_failed_reason():
    class FakeSeedance(SeedanceVideoAdapter):
        def _request_json(self, method, path, *, payload=None, params=None):
            return {
                "id": "cgt-task-4",
                "status": "failed",
                "error": {"code": "VideoGenerationFailed", "message": "生成失败：主体数量变化"},
            }

    adapter = FakeSeedance(
        api_key="seedance-test",
        base_url="https://ark.cn-beijing.volces.com/api/v3",
    )
    status = adapter.get_task_status("cgt-task-4")
    assert status["status"] == "failed"
    assert "主体数量变化" in status["fail_reason"]


def test_factory_selects_seedance_as_default_video_provider(monkeypatch):
    monkeypatch.setattr(settings, "ai_video_provider", "seedance")
    monkeypatch.setattr(settings, "seedance_api_key", "test-seedance-key")
    monkeypatch.setattr(settings, "ai_video_model", "doubao-seedance-1-0-pro-250528")
    _clear_adapter_caches()

    adapter = get_video_adapter()
    assert isinstance(adapter, SeedanceVideoAdapter)
    assert adapter.config["model"] == "doubao-seedance-1-0-pro-250528"
    assert adapter.config["base_url"] == settings.seedance_base_url

    _clear_adapter_caches()


# ============================================================
# Seedream（火山方舟 Ark 图生图）契约测试
# ============================================================


def _seedream_adapter(**kwargs):
    base = {
        "api_key": "seedream-test",
        "base_url": "https://ark.cn-beijing.volces.com/api/v3",
        "model": "doubao-seedream-4-5-251128",
        "size": "2K",
    }
    base.update(kwargs)
    return SeedreamImageAdapter(**base)


def test_seedream_capabilities():
    adapter = _seedream_adapter()
    caps = adapter.capabilities()
    assert caps["image_to_image"] is True
    assert caps["text_to_image"] is True
    assert caps["reference_image"] is True
    assert caps["multiple_variants"] is True
    assert caps["seed"] is True


def test_seedream_image_to_image_payload_contract():
    """图生图：image 参数传 base64 Data URL，模型/尺寸来自配置，取 b64_json。"""
    calls: list[dict] = []
    encoded = base64.b64encode(_png()).decode("ascii")

    class FakeSeedream(SeedreamImageAdapter):
        def _request_json(self, payload):
            calls.append(payload)
            return {"data": [{"b64_json": encoded, "url": None}]}

    adapter = FakeSeedream(
        api_key="seedream-test",
        base_url="https://ark.cn-beijing.volces.com/api/v3",
        model="doubao-seedream-4-5-251128",
        size="2K",
    )
    result = adapter.render_image(
        _png(),
        "建筑写实渲染，保持主体",
        negative_prompt="不得增加楼层",
        n=1,
        seed=8,
    )

    assert Image.open(io.BytesIO(result[0])).format == "PNG"
    payload = calls[0]
    assert payload["model"] == "doubao-seedream-4-5-251128"
    assert payload["size"] == "2K"
    assert payload["response_format"] == "b64_json"
    assert payload["watermark"] is False
    # 图生图通过 image 参数传参考图（base64 Data URL）
    assert payload["image"].startswith("data:image/png;base64,")
    # Seedream 4.5 无独立 negative_prompt 字段，负向约束并入正向提示词
    assert "不得增加楼层" in payload["prompt"]
    assert payload["seed"] == 8


def test_seedream_render_image_requires_source_no_fallback():
    """图生图未提供源图直接报错，不降级为文生图。"""
    adapter = _seedream_adapter()
    with pytest.raises(Exception) as exc:
        adapter.render_image(None, "图生图")
    assert "必须提供源图片" in str(exc.value)


def test_factory_selects_seedream_image_provider(monkeypatch):
    monkeypatch.setattr(settings, "ai_image_provider", "seedream")
    monkeypatch.setattr(settings, "seedream_api_key", "test-seedream-key")
    monkeypatch.setattr(settings, "ai_image_model", "doubao-seedream-4-5-251128")
    _clear_adapter_caches()

    adapter = get_image_adapter()
    assert isinstance(adapter, SeedreamImageAdapter)
    assert adapter.config["model"] == "doubao-seedream-4-5-251128"
    assert adapter.config["base_url"] == settings.seedream_base_url

    _clear_adapter_caches()


# ============================================================
# MiniMax H3（V2 接口 /v2/video_generation）契约测试
# ============================================================


def _h3_adapter(**kwargs):
    base = {
        "api_key": "minimax-test",
        "base_url": "https://api.minimaxi.com",
        "model": "MiniMax-H3",
        "resolution": "1080P",
        "poll_interval": 0,
        "video_timeout": 5,
    }
    base.update(kwargs)
    return MiniMaxH3VideoAdapter(**base)


def test_minimax_h3_capabilities():
    caps = _h3_adapter().capabilities()
    assert caps["image_to_video"] is True
    assert caps["first_last_frame_video"] is True
    assert caps["text_to_video"] is False  # 本期页面不开放文生视频
    assert caps["async_task"] is True


def test_minimax_h3_image_to_video_payload_contract():
    """H3 图生视频：POST /v2/video_generation，content 数组 text + first_frame。"""
    calls: list[dict] = []

    class FakeH3(MiniMaxH3VideoAdapter):
        def _request_json(self, method, path, *, payload=None, params=None):
            calls.append({"method": method, "path": path, "payload": payload})
            return {"task_id": "424010985738629"}

    adapter = FakeH3(
        api_key="minimax-test",
        base_url="https://api.minimaxi.com",
        model="MiniMax-H3",
        resolution="1080P",
    )
    task_id = adapter.create_generation_task(
        prompt="建筑缓慢推进",
        first_frame_bytes=_png(),
        mode="image_to_video",
        duration=5,
        aspect_ratio="adaptive",
    )

    assert task_id == "424010985738629"
    call = calls[0]
    assert call["method"] == "POST"
    assert call["path"] == "/v2/video_generation"
    payload = call["payload"]
    assert payload["model"] == "MiniMax-H3"
    assert payload["resolution"] == "2K"  # 1080P → 2K 映射
    assert payload["duration"] == 5
    assert payload["ratio"] == "adaptive"
    assert payload["aigc_watermark"] is False
    assert payload["content"][0] == {"type": "text", "text": "建筑缓慢推进"}
    first = payload["content"][1]
    assert first["type"] == "image_url"
    assert first["role"] == "first_frame"
    assert first["image_url"]["url"].startswith("data:image/png;base64,")


def test_minimax_h3_first_last_frame_order():
    """H3 首尾帧：content 顺序固定 [first_frame, last_frame]。"""
    calls: list[dict] = []
    first_png = _png(color=(10, 20, 30))
    last_png = _png(color=(200, 60, 90))

    class FakeH3(MiniMaxH3VideoAdapter):
        def _request_json(self, method, path, *, payload=None, params=None):
            calls.append(payload)
            return {"task_id": "t-1"}

    adapter = FakeH3(api_key="minimax-test", model="MiniMax-H3")
    adapter.create_generation_task(
        prompt="白模过渡到写实",
        first_frame_bytes=first_png,
        last_frame_bytes=last_png,
        mode="first_last_frame_video",
        duration=10,
    )
    payload = calls[0]
    roles = [item.get("role") for item in payload["content"][1:]]
    assert roles == ["first_frame", "last_frame"]
    assert payload["content"][1]["image_url"]["url"].endswith(
        base64.b64encode(first_png).decode("ascii")
    )
    assert payload["content"][2]["image_url"]["url"].endswith(
        base64.b64encode(last_png).decode("ascii")
    )


def test_minimax_h3_first_last_requires_two_images():
    adapter = _h3_adapter()
    with pytest.raises(Exception) as exc:
        adapter.create_generation_task(
            prompt="缺尾帧",
            first_frame_bytes=_png(),
            last_frame_bytes=None,
            mode="first_last_frame_video",
        )
    assert "首帧与尾帧" in str(exc.value)


def test_minimax_h3_poll_and_download():
    """H3 查询：GET /v2/query/video_generation/{task_id}，结果取 task.content.url。"""
    calls: list[tuple[str, str]] = []

    class FakeH3(MiniMaxH3VideoAdapter):
        def _request_json(self, method, path, *, payload=None, params=None):
            calls.append((method, path))
            if method == "POST":
                return {"task_id": "t-2"}
            return {
                "task": {
                    "id": "t-2",
                    "status": "succeeded",
                    "content": {"url": "https://example.invalid/h3.mp4"},
                }
            }

        def _download_video(self, url):
            assert url.endswith("h3.mp4")
            return b"h3-mp4"

    adapter = FakeH3(
        api_key="minimax-test",
        model="MiniMax-H3",
        poll_interval=0,
        video_timeout=5,
    )
    result = adapter.generate("缓慢推进", duration=5, first_frame_bytes=_png())
    assert result == b"h3-mp4"
    assert calls[0] == ("POST", "/v2/video_generation")
    assert calls[1] == ("GET", "/v2/query/video_generation/t-2")


def test_minimax_h3_failed_status_parses_error():
    class FakeH3(MiniMaxH3VideoAdapter):
        def _request_json(self, method, path, *, payload=None, params=None):
            return {
                "task": {
                    "id": "t-3",
                    "status": "failed",
                    "error": {"code": "1026", "message": "video description contains sensitive content"},
                }
            }

    adapter = FakeH3(api_key="minimax-test", model="MiniMax-H3")
    status = adapter.get_task_status("t-3")
    assert status["status"] == "failed"
    assert "sensitive content" in status["fail_reason"]


def test_factory_minimax_builds_h3_adapter(monkeypatch):
    monkeypatch.setattr(settings, "ai_video_provider", "minimax")
    monkeypatch.setattr(settings, "minimax_api_key", "test-minimax-key")
    monkeypatch.setattr(settings, "minimax_video_model", "MiniMax-H3")
    _clear_adapter_caches()

    adapter = get_video_adapter()
    assert isinstance(adapter, MiniMaxH3VideoAdapter)
    assert adapter.config["model"] == "MiniMax-H3"

    _clear_adapter_caches()


# ============================================================
# 火山引擎豆包语音合成（Volcengine Doubao Speech）契约测试
# ============================================================


def _volc_tts_adapter(**kwargs):
    base = {
        "api_key": "volc-tts-test-key",
        "base_url": "https://openspeech.bytedance.com/api/v3/tts/unidirectional/sse",
        "resource_id": "seed-tts-2.0",
        "voice": "zh_female_xiaohe_uranus_bigtts",
        "timeout": 30,
    }
    base.update(kwargs)
    return VolcengineTTSAdapter(**base)


def test_volcengine_tts_capabilities_and_voices():
    adapter = _volc_tts_adapter()
    caps = adapter.capabilities()
    assert caps["synthesize"] is True
    assert caps["speed_control"] is True
    assert caps["pitch_control"] is True
    assert caps["voice_preview"] is True
    assert caps["mp3"] is True
    assert caps["wav"] is True
    assert caps["ssml"] is False  # 火山豆包 SSE 不支持 SSML
    voices = adapter.list_voices()
    assert any(v["id"] == "zh_female_xiaohe_uranus_bigtts" for v in voices)
    assert any(v["id"] == "zh_male_m191_uranus_bigtts" for v in voices)


def test_volcengine_tts_synthesize_sse_contract():
    """火山豆包 TTS：POST SSE，X-Api-Key + X-Api-Resource-Id 鉴权，body 结构正确。"""
    captured = {}
    fake_mp3 = b"ID3fake-mp3-bytes"

    class FakeVolcTTS(VolcengineTTSAdapter):
        def _endpoint(self):
            return "https://test.invalid/sse"

        def _stream_sse(self, headers, body):
            captured["headers"] = headers
            captured["body"] = body
            # 模拟两条 SSE data 事件，拼接 base64 音频
            import base64 as _b64
            import json as _json

            chunk1 = _b64.b64encode(fake_mp3[:5]).decode()
            chunk2 = _b64.b64encode(fake_mp3[5:]).decode()
            return [
                f"data: {_json.dumps({'code': 0, 'data': chunk1})}",
                f"data: {_json.dumps({'code': 0, 'data': chunk2})}",
            ]

    adapter = FakeVolcTTS(
        api_key="volc-tts-test-key",
        resource_id="seed-tts-2.0",
        voice="zh_male_m191_uranus_bigtts",
    )
    audio = adapter.synthesize("你好，这是测试配音。", speed=1.0, format="mp3")

    assert audio == fake_mp3
    assert captured["headers"]["X-Api-Key"] == "volc-tts-test-key"
    assert captured["headers"]["X-Api-Resource-Id"] == "seed-tts-2.0"
    req = captured["body"]["req_params"]
    assert req["text"] == "你好，这是测试配音。"
    assert req["speaker"] == "zh_male_m191_uranus_bigtts"
    assert req["audio_params"]["format"] == "mp3"
    assert req["audio_params"]["speech_rate"] == 0  # speed 1.0 -> 0


def test_volcengine_tts_speed_mapping():
    adapter = _volc_tts_adapter()
    assert adapter._speech_rate(1.0) == 0
    assert adapter._speech_rate(1.5) == 50
    assert adapter._speech_rate(0.5) == -50
    assert adapter._speech_rate(2.0) == 100


def test_volcengine_tts_wav_format_uses_any_audio_to_wav():
    """format='wav' 时通过 any_audio_to_wav 把 mp3 转 wav（豆包不直接返回 wav）。"""
    import base64 as _b64
    import io
    import json as _json

    import wave

    # 构造一个最小 WAV 字节，模拟 any_audio_to_wav 的产物
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(48000)
        wf.writeframes(b"\x00\x00" * 10)
    wav_bytes = buf.getvalue()

    class FakeVolcTTS(VolcengineTTSAdapter):
        def _endpoint(self):
            return "https://test.invalid/sse"

        def _stream_sse(self, headers, body):
            return [f"data: {_json.dumps({'code': 0, 'data': _b64.b64encode(wav_bytes).decode()})}"]

    adapter = FakeVolcTTS(api_key="volc-tts-test-key")
    audio = adapter.synthesize("测试", format="wav")
    assert audio == wav_bytes


def test_volcengine_tts_error_propagation():
    import json as _json

    class FakeVolcTTS(VolcengineTTSAdapter):
        def _endpoint(self):
            return "https://test.invalid/sse"

        def _stream_sse(self, headers, body):
            return [f"data: {_json.dumps({'code': 10002, 'message': 'balance insufficient'})}"]

    adapter = FakeVolcTTS(api_key="volc-tts-test-key")
    import pytest as _pytest

    with _pytest.raises(Exception) as exc:
        adapter.synthesize("测试", format="mp3")
    assert "火山豆包" in str(exc.value)


def test_factory_selects_volcengine_tts(monkeypatch):
    monkeypatch.setattr(settings, "ai_tts_provider", "volcengine")
    monkeypatch.setattr(settings, "volcengine_tts_api_key", "volc-tts-test-key")
    _clear_adapter_caches()

    adapter = get_tts_adapter()
    assert isinstance(adapter, VolcengineTTSAdapter)
    assert adapter.config["api_key"] == "volc-tts-test-key"

    _clear_adapter_caches()
