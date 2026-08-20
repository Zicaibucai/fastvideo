"""OCR 适配器：MockOCRAdapter + TesseractOCRAdapter。

扫描版 PDF 页面会调用 OCR 识别。OCR 不可用时不得导致整个文档解析失败，
应标记页面状态并允许后续重试。
"""

from __future__ import annotations

from typing import Any

from app.adapters.base import BaseAIAdapter, MockMixin
from app.core.logging import get_logger

logger = get_logger(__name__)


class BaseOCRAdapter(BaseAIAdapter):
    """OCR 基类。"""

    provider = "base"

    def is_available(self) -> bool:
        return False

    def ocr_image(self, image_bytes: bytes, *, lang: str = "chi_sim+eng") -> dict[str, Any]:
        """识别单张图片，返回 {text, confidence}。"""
        raise NotImplementedError

    def ocr_pdf_page(self, pdf_bytes: bytes, page_index: int) -> dict[str, Any]:
        """从 PDF 渲染第 page_index(0-based) 页并 OCR，返回 {text, confidence}。"""
        raise NotImplementedError


class TesseractOCRAdapter(BaseOCRAdapter):
    """基于 Tesseract 的实现（可选安装）。"""

    provider = "tesseract"

    def is_available(self) -> bool:
        import shutil

        return shutil.which("tesseract") is not None

    def ocr_image(self, image_bytes: bytes, *, lang: str = "chi_sim+eng") -> dict[str, Any]:
        import subprocess
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            img_path = f"{tmp}/page.png"
            with open(img_path, "wb") as f:
                f.write(image_bytes)
            cmd = ["tesseract", img_path, f"{tmp}/out", "-l", lang, "--psm", "6"]
            try:
                subprocess.run(cmd, check=True, capture_output=True, timeout=120)
                with open(f"{tmp}/out.txt", "r", encoding="utf-8") as f:
                    text = f.read()
                return {"text": text, "confidence": 0.8}
            except subprocess.CalledProcessError as exc:
                logger.warning("tesseract_failed", stderr=exc.stderr.decode()[:300])
                return {"text": "", "confidence": 0.0}

    def ocr_pdf_page(self, pdf_bytes: bytes, page_index: int) -> dict[str, Any]:
        import io

        import pdfplumber

        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            page = pdf.pages[page_index]
            img = page.to_image(resolution=200)
            png_bytes = img.original.convert("RGB")
            buf = io.BytesIO()
            png_bytes.save(buf, format="PNG")
            return self.ocr_image(buf.getvalue())


class MockOCRAdapter(TesseractOCRAdapter, MockMixin):
    """Mock OCR：返回占位文本，保证流程可运行。

    无 Tesseract 时也可用，返回带页码的演示文本。
    """

    provider = "mock"

    def is_available(self) -> bool:
        return True

    def ocr_image(self, image_bytes: bytes, *, lang: str = "chi_sim+eng") -> dict[str, Any]:
        return {
            "text": "【OCR演示文本】本页为扫描件，由系统以演示模式完成文字识别。工程投标项目关键信息见后续文本。",
            "confidence": 0.35,
        }

    def ocr_pdf_page(self, pdf_bytes: bytes, page_index: int) -> dict[str, Any]:
        return {
            "text": f"【OCR演示文本·第{page_index + 1}页】本页为扫描件，系统以演示模式完成识别。",
            "confidence": 0.35,
        }
