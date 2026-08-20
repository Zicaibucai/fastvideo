"""图片处理工具：上传校验、EXIF 处理、缩略图、结构一致性辅助检查、Mock 渲染效果。

所有 Mock 渲染效果使用 Pillow 确定性生成，输出真实可访问的 PNG 文件。
"""

from __future__ import annotations

import hashlib
import io
import re
from typing import Any

from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageOps

from app.core.logging import get_logger

logger = get_logger(__name__)

# 上传限制
MAX_IMAGE_SIZE = 30 * 1024 * 1024  # 30MB
MIN_WIDTH = 640
MIN_HEIGHT = 360
MAX_PIXELS = 80_000_000  # 防止解压炸弹

ALLOWED_IMAGE_TYPES = {"jpg", "jpeg", "png", "webp"}
ALLOWED_MIME = {
    "image/jpeg": "jpeg",
    "image/png": "png",
    "image/webp": "webp",
}

# 系统级 AI 免责声明
AI_DISCLAIMER = (
    "AI渲染图仅用于视觉表达。工程尺寸、构件位置、施工顺序和技术参数"
    "以原始模型、图纸及施工方案为准。"
)

# 系统级结构保持提示（PromptBuilder 使用）
SYSTEM_STRUCTURE_PROMPT = (
    "严格以输入模型截图作为空间与结构参考，保持建筑主体数量、体量、轮廓、层数、"
    "道路关系、主要门窗和设备位置。只优化材质、灯光、环境、景观、天气和画面质感，"
    "不重新设计建筑。"
)

SYSTEM_NEGATIVE_PROMPT = (
    "禁止改变建筑主体数量，禁止增加或删除楼层，禁止改变建筑轮廓，禁止改变柱网，"
    "禁止移动主要门窗，禁止改变道路走向，禁止移动主要设备，禁止生成不合理施工机械，"
    "禁止修改企业Logo，禁止生成乱码文字，禁止虚构工程标牌，禁止出现严重透视错误，"
    "禁止主体建筑变形，禁止重复车辆和人物，禁止低清晰度。"
)


class ImageValidationError(Exception):
    """图片校验失败。"""


# ============================================================
# 上传校验
# ============================================================

def safe_filename(name: str) -> str:
    name = name.replace("\\", "/").split("/")[-1]
    name = "".join(c for c in name if c not in '<>:"|?*')
    return name.strip() or "未命名图片"


def validate_and_process_image(
    data: bytes,
    filename: str,
) -> dict[str, Any]:
    """校验并处理上传的模型截图。

    返回 {sha256, width, height, color_mode, aspect_ratio, mime_type, file_type, processed_data}
    自动处理 EXIF 方向、去除 EXIF 隐私信息、校验尺寸与像素数。
    禁止 SVG。
    """
    if len(data) > MAX_IMAGE_SIZE:
        raise ImageValidationError(f"文件超过 {MAX_IMAGE_SIZE // 1024 // 1024}MB 上限")

    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if ext == "svg":
        raise ImageValidationError("禁止上传 SVG 作为模型截图")
    if ext not in ALLOWED_IMAGE_TYPES:
        raise ImageValidationError(f"不支持的文件类型 .{ext}，支持 JPG/PNG/WEBP")

    # 校验真实格式
    try:
        img = Image.open(io.BytesIO(data))
        img.load()
    except Exception:
        raise ImageValidationError("文件不是有效的图片格式")

    fmt = (img.format or "").lower()
    if fmt not in ("jpeg", "png", "webp"):
        raise ImageValidationError(f"实际图片格式 {fmt} 不支持")

    # 解压炸弹防护（先检查原始尺寸）
    width, height = img.size
    if width * height > MAX_PIXELS:
        raise ImageValidationError(
            f"图片像素数 {width * height} 超过上限 {MAX_PIXELS}"
        )

    # EXIF 方向处理 + 去除 EXIF 隐私信息
    img = ImageOps.exif_transpose(img)
    width, height = img.size  # 转置后重新取尺寸

    if width < MIN_WIDTH or height < MIN_HEIGHT:
        raise ImageValidationError(
            f"图片尺寸 {width}×{height} 小于最小要求 {MIN_WIDTH}×{MIN_HEIGHT}"
        )

    # 去除 EXIF 隐私信息
    img.info.pop("exif", None)
    img = img.convert("RGB" if img.mode != "RGBA" else "RGBA")

    # 重新编码（去除 EXIF）
    out_buf = io.BytesIO()
    if fmt == "jpeg":
        img.save(out_buf, format="JPEG", quality=92, exif=b"")
    elif fmt == "webp":
        img.save(out_buf, format="WEBP", quality=90)
    else:
        img.save(out_buf, format="PNG")
    processed = out_buf.getvalue()

    return {
        "sha256": hashlib.sha256(processed).hexdigest(),
        "width": width,
        "height": height,
        "color_mode": img.mode,
        "aspect_ratio": _aspect_ratio_str(width, height),
        "mime_type": "image/png" if fmt == "png" else f"image/{fmt}",
        "file_type": fmt,
        "processed_data": processed,
        "image": img,
    }


def _aspect_ratio_str(width: int, height: int) -> str:
    import math

    g = math.gcd(width, height)
    return f"{width // g}:{height // g}"


def make_thumbnail(img: Image.Image, max_size: int = 320) -> bytes:
    thumb = img.copy()
    thumb.thumbnail((max_size, max_size), Image.LANCZOS)
    buf = io.BytesIO()
    thumb.save(buf, format="PNG")
    return buf.getvalue()


def encode_png(img: Image.Image) -> bytes:
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


# ============================================================
# 结构一致性辅助检查
# ============================================================

def quality_check(source_bytes: bytes, result_bytes: bytes) -> dict[str, Any]:
    """对源图和结果图执行基础自动检查（辅助检查，非工程准确性证明）。

    返回 quality_status / structure_similarity_score / edge_overlap_score /
    change_ratio / warnings
    """
    warnings: list[str] = []
    try:
        src = Image.open(io.BytesIO(source_bytes)).convert("L")
        res = Image.open(io.BytesIO(result_bytes)).convert("L")
    except Exception:
        return {
            "quality_status": "failed",
            "structure_similarity_score": 0.0,
            "edge_overlap_score": 0.0,
            "change_ratio": 1.0,
            "warnings": ["结果图不是有效图片"],
        }

    src = src.resize((256, 144), Image.LANCZOS)
    res = res.resize((256, 144), Image.LANCZOS)

    # 全黑或全白检测
    src_hist = src.histogram()
    res_hist = res.histogram()
    if _is_uniform(res_hist):
        warnings.append("结果图疑似全黑或全白")
        return {
            "quality_status": "failed",
            "structure_similarity_score": 0.0,
            "edge_overlap_score": 0.0,
            "change_ratio": 1.0,
            "warnings": warnings,
        }

    # 灰度结构相似度（简单实现：均值+方差+相关系数）
    import numpy as np

    src_arr = np.asarray(src, dtype=np.float32) / 255.0
    res_arr = np.asarray(res, dtype=np.float32) / 255.0

    mean_s, mean_r = src_arr.mean(), res_arr.mean()
    var_s = src_arr.var() + 1e-10
    var_r = res_arr.var() + 1e-10
    cov = ((src_arr - mean_s) * (res_arr - mean_r)).mean()
    # SSIM 简化
    c1, c2 = (0.01 * 255 / 255) ** 2, (0.03 * 255 / 255) ** 2
    ssim = ((2 * mean_s * mean_r + c1) * (2 * cov + c2)) / (
        (mean_s**2 + mean_r**2 + c1) * (var_s + var_r + c2)
    )
    ssim = float(max(0.0, min(1.0, ssim)))

    # 边缘轮廓重合度（Sobel 简化）
    src_edge = _sobel_magnitude(src_arr)
    res_edge = _sobel_magnitude(res_arr)
    edge_overlap = float(
        1.0 - (np.abs(src_edge - res_edge).mean())
    )

    # 主要区域变化比例
    diff = float(np.abs(src_arr - res_arr).mean())

    # 判定
    if ssim < 0.3 or diff > 0.8:
        status = "failed"
        warnings.append("结构相似度过低或变化过大")
    elif ssim < 0.6 or diff > 0.5:
        status = "warning"
        warnings.append("结构相似度偏低，请人工审核")
    else:
        status = "passed"

    return {
        "quality_status": status,
        "structure_similarity_score": round(ssim, 3),
        "edge_overlap_score": round(edge_overlap, 3),
        "change_ratio": round(diff, 3),
        "warnings": warnings,
    }


def _is_uniform(hist: list[int]) -> bool:
    """判断直方图是否集中在极值（全黑或全白）。"""
    total = sum(hist)
    if total == 0:
        return True
    # 灰度 0-255，取前5%和后5%
    dark = sum(hist[:13]) / total
    bright = sum(hist[-13:]) / total
    return dark > 0.95 or bright > 0.95


def _sobel_magnitude(arr) -> Any:
    """简化 Sobel 边缘检测（用 numpy 实现，可选 scipy 加速）。"""
    import numpy as np

    try:
        from scipy import ndimage

        gx = ndimage.sobel(arr, axis=1)
        gy = ndimage.sobel(arr, axis=0)
        return np.hypot(gx, gy)
    except ImportError:
        # 无 scipy 时用简单差分
        gx = np.abs(np.diff(arr, axis=1, append=arr[:, -1:]))
        gy = np.abs(np.diff(arr, axis=0, append=arr[-1:, :]))
        return np.clip(gx + gy, 0, 1)


# ============================================================
# Mock 渲染效果（确定性）
# ============================================================

def mock_render_image(
    source_bytes: bytes,
    *,
    style: str = "科技蓝",
    seed: int | None = None,
    operation: str = "render",
    mask_bytes: bytes | None = None,
    output_width: int | None = None,
    output_height: int | None = None,
) -> tuple[bytes, dict[str, Any]]:
    """Mock 渲染：保持原图主体与尺寸关系，应用确定性色彩分级/滤镜。

    相同 seed 与参数可获得可复现结果。返回 (png_bytes, metrics)。
    Mock 效果带"Mock Render"标记，不伪装成真实 AI 结果。
    """
    img = Image.open(io.BytesIO(source_bytes)).convert("RGB")
    width, height = img.size

    # 确定性的随机数
    rng = __import__("random").Random(seed if seed is not None else 0)

    if operation == "outpaint":
        # 扩图：用目标尺寸 + 模糊背景延展
        tw, th = output_width or width, output_height or height
        tw = max(tw, width)
        th = max(th, height)
        canvas = Image.new("RGB", (tw, th))
        bg = img.filter(ImageFilter.GaussianBlur(30))
        canvas.paste(bg, ((tw - width) // 2, (th - height) // 2))
        canvas.paste(img, ((tw - width) // 2, (th - height) // 2))
        img = canvas
    elif operation == "upscale":
        # 清晰度增强：输出更大尺寸
        scale = 2
        tw = output_width or (width * scale)
        th = output_height or (height * scale)
        img = img.resize((max(tw, width), max(th, height)), Image.LANCZOS)
    else:
        # render / inpaint
        if operation == "inpaint" and mask_bytes:
            img = _apply_mask_blur(img, mask_bytes)

    # 风格滤镜（确定性）
    img = _apply_style_filter(img, style, rng)

    # 轻微锐化
    img = img.filter(ImageFilter.SHARPEN)
    # 亮度和对比度
    img = ImageEnhance.Brightness(img).enhance(1.05)
    img = ImageEnhance.Contrast(img).enhance(1.08)

    # 添加 Mock 标记（右下角小字）
    draw = ImageDraw.Draw(img)
    draw.rectangle(
        [img.width - 130, img.height - 24, img.width - 4, img.height - 4],
        fill=(30, 30, 60),
    )
    draw.text((img.width - 124, img.height - 18), "Mock Render", fill=(255, 255, 255))

    return encode_png(img), {"width": img.width, "height": img.height}


def _apply_mask_blur(img: Image.Image, mask_bytes: bytes) -> Image.Image:
    """局部重绘 Mock：遮罩区域做模糊/色调调整，明确标记为 Mock。"""
    try:
        mask = Image.open(io.BytesIO(mask_bytes)).convert("L").resize(img.size, Image.NEAREST)
    except Exception:
        return img
    # 遮罩区域模糊
    blurred = img.filter(ImageFilter.GaussianBlur(6))
    # 色调偏绿（模拟增加绿化）
    r, g, b = blurred.split()
    g = g.point(lambda x: min(255, int(x * 1.12)))
    blurred = Image.merge("RGB", (r, g, b))
    return Image.composite(blurred, img, mask)


def _apply_style_filter(img: Image.Image, style: str, rng) -> Image.Image:
    """应用风格滤镜（确定性）。"""
    style_key = style
    if "科技" in style or "科技蓝" in style:
        # 科技蓝：增强蓝色
        r, g, b = img.split()
        r = r.point(lambda x: int(x * 0.9))
        b = b.point(lambda x: min(255, int(x * 1.15)))
        img = Image.merge("RGB", (r, g, b))
    elif "夜景" in style:
        img = ImageEnhance.Brightness(img).enhance(0.75)
        r, g, b = img.split()
        b = b.point(lambda x: int(x * 1.1))
        img = Image.merge("RGB", (r, g, b))
    elif "日景" in style or "写实" in style:
        img = ImageEnhance.Color(img).enhance(1.15)
    elif "白模" in style:
        # 白模：灰度 + 提亮
        gray = ImageOps.grayscale(img)
        gray = ImageEnhance.Brightness(gray).enhance(1.1)
        img = gray.convert("RGB")
    elif "绿色" in style:
        r, g, b = img.split()
        g = g.point(lambda x: min(255, int(x * 1.1)))
        img = Image.merge("RGB", (r, g, b))
    # 其它风格：轻微色调
    return img


# ============================================================
# 演示源图生成（Pillow 白模示意）
# ============================================================

def generate_demo_model_shot(
    kind: str, seed: int | None = None, size: tuple[int, int] = (1280, 720)
) -> bytes:
    """程序生成简化的建筑白模示意图作为演示源图（不下载网络图片）。"""
    rng = __import__("random").Random(seed if seed is not None else 0)
    width, height = size
    img = Image.new("RGB", (width, height), (245, 247, 250))
    draw = ImageDraw.Draw(img)

    sky = Image.new("RGB", (width, int(height * 0.35)), (215, 228, 242))
    img.paste(sky, (0, 0))
    # 地面
    ground = Image.new("RGB", (width, int(height * 0.2)), (228, 233, 235))
    img.paste(ground, (0, int(height * 0.8)))

    if kind == "total_plan":
        # 总平面鸟瞰：矩形建筑体块 + 道路
        for _ in range(6):
            x = rng.randint(60, width - 200)
            y = rng.randint(140, height - 160)
            w = rng.randint(90, 220)
            h = rng.randint(60, 140)
            draw.rectangle([x, y, x + w, y + h], fill=(190, 200, 210), outline=(120, 135, 150), width=2)
        # 道路
        draw.line([(0, height // 2), (width, height // 2)], fill=(150, 165, 180), width=18)
        draw.line([(width // 2, 0), (width // 2, height)], fill=(150, 165, 180), width=18)
        draw.text((30, 40), "总平面鸟瞰 DEMO", fill=(90, 100, 115))
    elif kind == "building_perspective":
        # 建筑人视：主楼体块
        base_y = int(height * 0.75)
        bw = int(width * 0.4)
        bh = int(height * 0.5)
        bx = (width - bw) // 2
        draw.rectangle([bx, base_y - bh, bx + bw, base_y], fill=(205, 213, 222), outline=(120, 135, 150), width=3)
        # 窗户网格
        for wx in range(bx + 12, bx + bw - 12, 26):
            for wy in range(base_y - bh + 12, base_y - 12, 22):
                draw.rectangle([wx, wy, wx + 12, wy + 12], fill=(160, 175, 190))
        draw.text((30, 30), "建筑人视 DEMO", fill=(90, 100, 115))
    else:
        # 施工阶段：塔吊 + 在建楼体
        base_y = int(height * 0.78)
        bw = int(width * 0.35)
        bh = int(height * 0.42)
        bx = int(width * 0.15)
        draw.rectangle([bx, base_y - bh, bx + bw, base_y], fill=(200, 210, 220), outline=(120, 135, 150), width=3)
        # 塔吊
        crane_x = bx + bw + 40
        draw.line([(crane_x, base_y), (crane_x, base_y - 240)], fill=(90, 100, 115), width=6)
        draw.line([(crane_x, base_y - 240), (crane_x + 160, base_y - 240)], fill=(90, 100, 115), width=6)
        draw.line([(crane_x + 160, base_y - 240), (crane_x, base_y - 180)], fill=(90, 100, 115), width=3)
        draw.text((30, 30), "施工阶段 DEMO", fill=(90, 100, 115))

    return encode_png(img)
