#!/usr/bin/env bash
# 停止本地开发服务，不影响 Redis 和数据库数据。
set -u
for port in 5173 8000; do
  pids="$(lsof -tiTCP:"$port" -sTCP:LISTEN 2>/dev/null || true)"
  [[ -z "$pids" ]] || kill $pids 2>/dev/null || true
done
sleep 1
for port in 5173 8000; do
  pids="$(lsof -tiTCP:"$port" -sTCP:LISTEN 2>/dev/null || true)"
  [[ -z "$pids" ]] || kill -KILL $pids 2>/dev/null || true
done
echo "前端和后端已停止；Redis、SQLite 数据和素材文件未删除。"
