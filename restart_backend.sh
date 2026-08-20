#!/bin/bash
# FastVideo 后端重启自检脚本：杀掉残留 → 启动 → 验证 ai-video 接口
set -e
cd /Users/apple/Documents/中建实习/第六周/fastvideo/backend
source .venv-local/bin/activate

echo "== 1) 清理 8000 端口残留进程 =="
lsof -ti:8000 | xargs kill -9 2>/dev/null || true
sleep 1

echo "== 2) 启动后端（日志写入 /tmp/fastvideo_backend.log）=="
nohup uvicorn app.main:app --port 8000 > /tmp/fastvideo_backend.log 2>&1 &
sleep 5

echo "== 3) 健康检查 =="
curl -s http://localhost:8000/api/v1/health || { echo "后端未起来，日志如下："; tail -30 /tmp/fastvideo_backend.log; exit 1; }
echo

echo "== 4) 登录并建项目验证 ai-video 接口 =="
TOKEN=$(curl -s -X POST http://localhost:8000/api/v1/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"email":"admin@fastvideo.cn","password":"admin123456"}' | python3 -c "import sys,json;print(json.load(sys.stdin)['access_token'])")

PID=$(curl -s -X POST http://localhost:8000/api/v1/projects \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"name":"自检项目","code":"SELF-CHECK"}' | python3 -c "import sys,json;print(json.load(sys.stdin)['id'])")

for ep in templates providers reference-images; do
  CODE=$(curl -s -o /dev/null -w "%{http_code}" \
    http://localhost:8000/api/v1/projects/$PID/ai-video/$ep \
    -H "Authorization: Bearer $TOKEN")
  echo "GET /ai-video/$ep -> HTTP $CODE"
done

echo "== 5) 模板数量 =="
curl -s http://localhost:8000/api/v1/projects/$PID/ai-video/templates \
  -H "Authorization: Bearer $TOKEN" | python3 -c "import sys,json;d=json.load(sys.stdin);print(f'模板数: {len(d)}');[print(' -',t['name']) for t in d[:5]]"

echo
echo "✅ 全部 200 即正常。后端已在后台运行（日志：/tmp/fastvideo_backend.log）"
echo "   如需停止：lsof -ti:8000 | xargs kill -9"
