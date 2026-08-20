# 后端镜像（API + Celery Worker 共用）
FROM python:3.11-slim

WORKDIR /app

# 系统依赖（FFmpeg 用于视频/音频生成与合成）
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    fontconfig \
    fonts-noto-cjk \
    libpq-dev \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Python 依赖
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 应用代码
COPY app ./app
COPY alembic ./alembic
COPY alembic.ini .

EXPOSE 8000

# 默认命令（docker-compose 中会被覆盖为 worker 命令）
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
