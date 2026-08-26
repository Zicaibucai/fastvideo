"""pytest 共享配置：在导入 app 之前固定测试环境变量。"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

_TEST_ROOT = Path(tempfile.mkdtemp(prefix="fastvideo-tests-"))
_TEST_STORAGE = _TEST_ROOT / "storage"
_TEST_DB = _TEST_ROOT / "test.db"
_TEST_STORAGE.mkdir(parents=True, exist_ok=True)

os.environ["DATABASE_URL"] = f"sqlite:///{_TEST_DB}"
os.environ["USE_CELERY"] = "false"
os.environ["AI_LLM_PROVIDER"] = "disabled"
os.environ["AI_IMAGE_PROVIDER"] = "disabled"
os.environ["AI_VIDEO_PROVIDER"] = "disabled"
os.environ["AI_TTS_PROVIDER"] = "disabled"
os.environ["STORAGE_BACKEND"] = "local"
os.environ["STORAGE_LOCAL_DIR"] = str(_TEST_STORAGE)
