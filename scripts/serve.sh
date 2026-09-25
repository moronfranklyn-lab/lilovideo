#!/usr/bin/env bash
# Lilovideo 单端口运行（用户模式）
#
# 用法：
#   bash scripts/serve.sh              # 构建（如需）→ 起后端 → 开浏览器
#   bash scripts/serve.sh --rebuild    # 强制重新构建前端
#   bash scripts/serve.sh --no-open    # 不起浏览器
#
# 与 launch.sh 的区别
# ------------------
#   serve.sh（本脚本）  前端静态产物由**后端一起托管** → 只有一个进程、一个端口。
#                       前端与后端同源，不需要任何代理规则，运行时也不需要 Node。
#                       这是给使用者的模式。
#   launch.sh           前端跑 `next dev`（:3000）+ 后端（:8000），带热更新。
#                       这是给开发者的模式。
#
# 为什么单端口更重要，不只是"少一个端口"
# --------------------------------------
# 前端原先靠 `rewrites()` 把 30 条 `/api/*` 逐条代理到后端，而这套代理
# 漏配过**三次**（/api/cost/*、/api/credits/*、/api/models/*），症状都是
# 「直连后端 200、经前端 404」。同源之后这一整类问题从根上不存在了。
set -u

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKEND_DIR="$ROOT/src/backend"
FRONTEND_DIR="$ROOT/src/frontend"

BACKEND_PORT="${LILOVIDEO_BACKEND_PORT:-8000}"
APP_URL="http://127.0.0.1:$BACKEND_PORT"

LOG_DIR="$(printf '%s' "${TMPDIR:-/tmp}" | sed 's:/*$::')/lilovideo"
mkdir -p "$LOG_DIR"
API_LOG="$LOG_DIR/backend.log"
API_PID="$LOG_DIR/backend.pid"
WEB_PID="$LOG_DIR/frontend.pid"

REBUILD=0
OPEN_BROWSER=1
for arg in "$@"; do
  case "$arg" in
    --rebuild) REBUILD=1 ;;
    --no-open) OPEN_BROWSER=0 ;;
    -h|--help) sed -n '2,10p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "未知参数：${arg}（用 --help 看用法）" >&2; exit 2 ;;
  esac
done

info() { printf '[Lilovideo] %s\n' "$1"; }
warn() { printf '[Lilovideo] 注意：%s\n' "$1" >&2; }
fail() { printf '[Lilovideo] 错误：%s\n' "$1" >&2; exit 1; }

DIST_DIR="$FRONTEND_DIR/out"

backend_healthy() {
  local code
  code="$(curl -sS -o /dev/null -w '%{http_code}' --max-time 3 "$APP_URL/api/health" 2>/dev/null || echo 000)"
  [ "$code" = "200" ]
}

open_url() {
  [ "$OPEN_BROWSER" -eq 1 ] || return 0
  if command -v open >/dev/null 2>&1; then open "$1" >/dev/null 2>&1 || true
  elif command -v xdg-open >/dev/null 2>&1; then xdg-open "$1" >/dev/null 2>&1 || true
  else info "请手动在浏览器打开：$1"; fi
}

# ---------- 1. 依赖自检 ----------

[ -x "$BACKEND_DIR/.venv/bin/python" ] || [ -x "$BACKEND_DIR/.venv/Scripts/python.exe" ] || fail \
"后端虚拟环境不存在。请先执行安装：
    cd src && bash install.sh"

# ---------- 2. 前端产物 ----------

if [ "$REBUILD" -eq 1 ]; then
  info "按要求重新构建前端…"
  ( cd "$FRONTEND_DIR" && NEXT_OUTPUT=export npm run build ) || fail "前端构建失败，请查看上面的输出。"
elif [ ! -f "$DIST_DIR/index.html" ]; then
  [ -d "$FRONTEND_DIR/node_modules" ] || fail \
"前端依赖不存在，无法构建。请先执行安装：
    cd src && bash install.sh"
  info "首次运行需要构建前端（约 1 分钟）…"
  ( cd "$FRONTEND_DIR" && NEXT_OUTPUT=export npm run build ) || fail "前端构建失败，请查看上面的输出。"
  info "  构建完成 ✓"
fi

# ---------- 3. 已经在跑就复用 ----------

if backend_healthy; then
  # 进程在跑不等于跑的是**当前代码**。这个坑真实发生过：
  # 改了后端源码但复用旧进程，结果新加的接口一直 404，排查很久。
  if [ -f "$API_PID" ]; then
    newer="$(find "$BACKEND_DIR" -name '*.py' -not -path '*/.venv/*' -not -path '*/__pycache__/*' \
             -newer "$API_PID" -print -quit 2>/dev/null || true)"
    if [ -n "${newer:-}" ]; then
      warn "后端进程比源码旧（${newer#$BACKEND_DIR/} 有改动），它仍跑着旧代码。"
      warn "要加载新代码：bash scripts/stop.sh && bash scripts/serve.sh"
    fi
  fi
  info "服务已经在运行，直接打开浏览器。"
  info "  应用 $APP_URL"
  info "  停止 bash scripts/stop.sh"
  open_url "$APP_URL"
  exit 0
fi

# ---------- 4. 起后端（它同时提供前端） ----------

info "启动服务（:${BACKEND_PORT}，前端由后端一起托管）…"
( cd "$BACKEND_DIR" && exec nohup .venv/bin/python api_server.py >"$API_LOG" 2>&1 </dev/null ) &
echo $! >"$API_PID"

waited=0
while [ "$waited" -lt 90 ]; do
  backend_healthy && break
  sleep 1
  waited=$((waited + 1))
  [ $((waited % 10)) -eq 0 ] && info "  等待就绪… ${waited}s"
done

if ! backend_healthy; then
  echo
  warn "服务 90 秒内没有就绪。"
  [ -f "$API_LOG" ] && { echo "  --- $API_LOG 末尾 20 行 ---"; tail -20 "$API_LOG" | sed 's/^/  /'; }
  fail "启动失败。常见原因：端口被占、config.yaml 配置有误、依赖缺失。"
fi

# 确认前端真的被后端托管了（而不是只起了 API）
if ! curl -sS --max-time 10 "$APP_URL/" 2>/dev/null | grep -q "_next"; then
  warn "服务已起，但根路径看起来不是前端界面。"
  warn "请确认前端已构建：bash scripts/serve.sh --rebuild"
fi

# ---------- 5. 首次配置提示 ----------

CONFIG_FILE="$BACKEND_DIR/config.yaml"
if [ -f "$CONFIG_FILE" ] && ! grep -qE "api_key: *['\"]?[A-Za-z0-9]" "$CONFIG_FILE"; then
  echo
  info "还没有填写任何 API Key —— 打开页面后请先到「设置」页填写，否则生成会失败。"
fi

echo
info "就绪："
info "  应用  $APP_URL     ← 前端与接口都在这个地址"
info "  日志  $API_LOG"
info "  停止  bash scripts/stop.sh"
echo

open_url "$APP_URL"
