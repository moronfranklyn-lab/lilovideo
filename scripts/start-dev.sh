#!/usr/bin/env bash
# Lilovideo 本地开发一键启动（前端 + 后端）
# 用法: ./scripts/start-dev.sh
set -e
ROOT="$(cd "$(dirname "$0")/.." && pwd)"

echo "[1/2] 启动后端 API (:8000)..."
cd "$ROOT/src/backend"
if [ ! -d .venv ]; then
  echo "  .venv 不存在，请先创建: python3 -m venv .venv && .venv/bin/pip install -r requirements.txt"
  exit 1
fi
nohup .venv/bin/python api_server.py > /tmp/lilovideo-api.log 2>&1 &
echo $! > /tmp/lilovideo-api.pid
echo "  后端日志: /tmp/lilovideo-api.log (pid $(cat /tmp/lilovideo-api.pid))"

echo "[2/2] 启动前端 dev (:3000)..."
cd "$ROOT/src/frontend"
nohup npm run dev -- --webpack > /tmp/lilovideo-web.log 2>&1 &
echo $! > /tmp/lilovideo-web.pid
echo "  前端日志: /tmp/lilovideo-web.log (pid $(cat /tmp/lilovideo-web.pid))"

echo ""
echo "完成。前端 http://localhost:3000 ，后端 http://localhost:8000"
echo "停止: kill \$(cat /tmp/lilovideo-api.pid) \$(cat /tmp/lilovideo-web.pid)"
