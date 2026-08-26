#!/usr/bin/env bash
# 本地开发一键启动：Redis（已有则复用）+ Celery + FastAPI + Vite。
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")" && pwd)"
BACKEND_DIR="$ROOT_DIR/backend"
FRONTEND_DIR="$ROOT_DIR/frontend"
LOG_DIR="${TMPDIR:-/tmp}/fastvideo"
mkdir -p "$LOG_DIR"

BACKEND_PID=""
FRONTEND_PID=""
CELERY_PID=""

stop_port() {
  local port="$1"
  local pids
  pids="$(lsof -tiTCP:"$port" -sTCP:LISTEN 2>/dev/null || true)"
  if [[ -n "$pids" ]]; then
    echo "清理端口 ${port}：${pids}"
    kill $pids 2>/dev/null || true
    sleep 1
    local remaining
    remaining="$(lsof -tiTCP:"$port" -sTCP:LISTEN 2>/dev/null || true)"
    [[ -z "$remaining" ]] || kill -KILL $remaining 2>/dev/null || true
  fi
}

detect_lan_ip() {
  local iface ip
  # macOS 常用 Wi‑Fi / 有线网卡；优先取当前默认路由对应的网卡。
  iface="$(route get default 2>/dev/null | awk '/interface:/{print $2; exit}')"
  if [[ -n "${iface:-}" ]]; then
    ip="$(ipconfig getifaddr "$iface" 2>/dev/null || true)"
    if [[ "$ip" =~ ^([0-9]{1,3}\.){3}[0-9]{1,3}$ ]]; then
      echo "$ip"
      return 0
    fi
  fi
  for iface in en0 en1 bridge0; do
    ip="$(ipconfig getifaddr "$iface" 2>/dev/null || true)"
    if [[ "$ip" =~ ^([0-9]{1,3}\.){3}[0-9]{1,3}$ ]]; then
      echo "$ip"
      return 0
    fi
  done
  return 1
}

cleanup() {
  echo
  echo "正在停止本地开发服务…"
  [[ -z "$FRONTEND_PID" ]] || kill "$FRONTEND_PID" 2>/dev/null || true
  [[ -z "$BACKEND_PID" ]] || kill "$BACKEND_PID" 2>/dev/null || true
  [[ -z "$CELERY_PID" ]] || kill "$CELERY_PID" 2>/dev/null || true
  stop_port 5173
  stop_port 8000
}
trap cleanup INT TERM EXIT

if [[ -x "$BACKEND_DIR/.venv-local/bin/python" ]]; then
  PYTHON="$BACKEND_DIR/.venv-local/bin/python"
elif [[ -x "$BACKEND_DIR/.venv/bin/python" ]]; then
  PYTHON="$BACKEND_DIR/.venv/bin/python"
else
  PYTHON="python3"
fi

redis_ready=0
if command -v redis-cli >/dev/null 2>&1 && redis-cli ping >/dev/null 2>&1; then
  redis_ready=1
elif command -v brew >/dev/null 2>&1; then
  echo "Redis 未运行，尝试启动本机 Redis 服务…"
  brew services start redis >/dev/null 2>&1 || true
  for _ in {1..10}; do
    if redis-cli ping >/dev/null 2>&1; then
      redis_ready=1
      break
    fi
    sleep 1
  done
fi
if [[ "$redis_ready" != 1 ]]; then
  echo "Redis 未运行或未安装。请安装后执行 brew services start redis，再重试。" >&2
  exit 1
fi

if ! command -v npm >/dev/null 2>&1; then
  echo "未找到 npm，无法启动前端。" >&2
  exit 1
fi

stop_port 8000
stop_port 5173

echo "启动后端 API…"
(cd "$BACKEND_DIR" && exec "$PYTHON" run_dev.py) >"$LOG_DIR/backend.log" 2>&1 &
BACKEND_PID=$!

ready=0
for _ in {1..30}; do
  if curl -fsS --max-time 1 http://127.0.0.1:8000/api/v1/health >/dev/null 2>&1; then
    ready=1
    break
  fi
  sleep 1
done
if [[ "$ready" != 1 ]]; then
  echo "后端启动失败，日志：$LOG_DIR/backend.log" >&2
  tail -40 "$LOG_DIR/backend.log" >&2 || true
  exit 1
fi

if grep -Eiq '^[[:space:]]*USE_CELERY[[:space:]]*=[[:space:]]*(true|1|yes)' "$ROOT_DIR/.env" 2>/dev/null; then
  # 避免重复启动 worker：同一 Redis 队列只保留一个本地消费者。
  if pgrep -af 'celery(.*-A app\.tasks\.celery_app\.celery_app)? worker|app\.tasks\.celery_app\.celery_app worker' >/dev/null 2>&1; then
    echo "复用已有 Celery 队列。"
  else
    echo "启动 Celery 队列…"
    (cd "$BACKEND_DIR" && exec "$PYTHON" -m celery -A app.tasks.celery_app.celery_app worker --loglevel=info --concurrency=2) >"$LOG_DIR/celery.log" 2>&1 &
    CELERY_PID=$!
  fi
else
  echo "USE_CELERY 未启用，任务将由后端同步处理。"
fi

echo "启动前端…"
(cd "$FRONTEND_DIR" && exec npm run dev -- --host 0.0.0.0) >"$LOG_DIR/frontend.log" 2>&1 &
FRONTEND_PID=$!

LAN_IP="$(detect_lan_ip || true)"

echo
echo "✅ 前端：http://127.0.0.1:5173"
echo "✅ 后端：http://127.0.0.1:8000/docs"
if [[ -n "$LAN_IP" ]]; then
  echo "✅ 前端（内网）：http://${LAN_IP}:5173"
  echo "✅ 后端（内网）：http://${LAN_IP}:8000/docs"
else
  echo "⚠️ 未检测到内网 IP，请检查 Wi‑Fi/网线连接。"
fi
echo "✅ 日志目录：$LOG_DIR"
echo "按 Ctrl+C 可同时停止前端、后端和 Celery。"

wait
