#!/usr/bin/env bash
# Lilovideo 生产/联调启动（后端 API + 前端生产构建）
# 用法: ./scripts/start-prod.sh
# 前置: 已执行 npm run build 生成 .next 产物
set -e
ROOT="$(cd "$(dirname "$0")/.." && pwd)"

echo "[1/2] 启动后端 API (:8000)..."
cd "$ROOT/src/backend"
if [ ! -d .venv ]; then
  echo "  .venv 不存在，请先创建: python3 -m venv .venv && .venv/bin/pip install -r requirements.txt"
  exit 1
fi
# 生产建议用 uvicorn 多 worker；如 config.yaml server.port=8000 则由 api_server.py 自带
nohup .venv/bin/python api_server.py > /tmp/lilovideo-api.log 2>&1 &
echo $! > /tmp/lilovideo-api.pid
echo "  后端日志: /tmp/lilovideo-api.log (pid $(cat /tmp/lilovideo-api.pid))"

echo "[2/2] 启动前端生产服务 (:3000)..."
cd "$ROOT/src/frontend"
if [ ! -d .next ]; then
  echo "  未找到 .next，先执行 npm run build"
  exit 1
fi
nohup npm run start > /tmp/lilovideo-web.log 2>&1 &
echo $! > /tmp/lilovideo-web.pid
echo "  前端日志: /tmp/lilovideo-web.log (pid $(cat /tmp/lilovideo-web.pid))"

echo ""
echo "完成。前端 http://localhost:3000 ，后端 http://localhost:8000"
echo "停止: kill \$(cat /tmp/lilovideo-api.pid) \$(cat /tmp/lilovideo-web.pid)"
