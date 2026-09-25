#!/usr/bin/env bash
# Lilovideo 一键启动
#
# 用法：
#   bash scripts/launch.sh              # 启动（默认开发模式，无需先 build）
#   bash scripts/launch.sh --prod       # 生产模式（先 build，首屏更快，需等几分钟）
#   bash scripts/launch.sh --no-open    # 不起浏览器
#
# 这个脚本是给**下载后第一次使用**的人准备的，所以设计目标是「出错时知道怎么办」：
#   - 依赖没装齐 → 明确告诉你跑 install.sh，而不是让它跑到一半失败
#   - 已经在跑   → 不重复启动，直接开浏览器
#   - 端口被占   → 说清是哪个端口被谁占了
#   - 启动失败   → 打印日志末尾，而不是干等
set -u

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKEND_DIR="$ROOT/src/backend"
FRONTEND_DIR="$ROOT/src/frontend"

BACKEND_PORT="${LILOVIDEO_BACKEND_PORT:-8000}"
FRONTEND_PORT="${LILOVIDEO_FRONTEND_PORT:-3000}"
BACKEND_URL="http://127.0.0.1:$BACKEND_PORT"
FRONTEND_URL="http://127.0.0.1:$FRONTEND_PORT"

# 日志放临时目录：这是运行产物，不该出现在仓库里
LOG_DIR="$(printf '%s' "${TMPDIR:-/tmp}" | sed 's:/*$::')/lilovideo"
mkdir -p "$LOG_DIR"
API_LOG="$LOG_DIR/backend.log"
WEB_LOG="$LOG_DIR/frontend.log"
API_PID="$LOG_DIR/backend.pid"
WEB_PID="$LOG_DIR/frontend.pid"

MODE="dev"
OPEN_BROWSER=1
for arg in "$@"; do
  case "$arg" in
    --prod) MODE="prod" ;;
    --no-open) OPEN_BROWSER=0 ;;
    -h|--help) sed -n '2,12p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "未知参数：${arg}（用 --help 看用法）" >&2; exit 2 ;;
  esac
done

info() { printf '[Lilovideo] %s\n' "$1"; }
warn() { printf '[Lilovideo] 注意：%s\n' "$1" >&2; }
fail() { printf '[Lilovideo] 错误：%s\n' "$1" >&2; exit 1; }

# ---------- 小工具 ----------

# 端口是否有服务在监听。优先用 curl（install.sh 已依赖它），退化到 bash 的 /dev/tcp。
port_open() {
  local port="$1"
  if command -v curl >/dev/null 2>&1; then
    curl -sS -o /dev/null --max-time 2 "http://127.0.0.1:$port" 2>/dev/null && return 0
    return 1
  fi
  (exec 3<>"/dev/tcp/127.0.0.1/$port") 2>/dev/null && return 0
  return 1
}

backend_healthy() {
  local code
  code="$(curl -sS -o /dev/null -w '%{http_code}' --max-time 3 "$BACKEND_URL/api/health" 2>/dev/null || echo 000)"
  [ "$code" = "200" ]
}

# 判断端口上是**我们的**前端，而不是碰巧占着 3000 的别的程序。
# 认 Next.js 的资源路径 `_next`：这比"有 HTTP 响应"具体得多。
frontend_ready() {
  local body
  body="$(curl -sS --max-time 5 "$FRONTEND_URL/" 2>/dev/null)" || return 1
  [ -n "$body" ] && printf '%s' "$body" | grep -q "_next"
}

# 谁占着端口（尽力而为：没有 lsof 时只报端口号）
port_owner() {
  local port="$1"
  if command -v lsof >/dev/null 2>&1; then
    lsof -nP -iTCP:"$port" -sTCP:LISTEN 2>/dev/null | awk 'NR==2 {print $1" (pid "$2")"}'
  fi
}

wait_for() {
  local desc="$1" timeout="$2"; shift 2
  local waited=0
  while [ "$waited" -lt "$timeout" ]; do
    if "$@"; then return 0; fi
    sleep 1
    waited=$((waited + 1))
    if [ $((waited % 10)) -eq 0 ]; then info "  等待${desc}… ${waited}s"; fi
  done
  return 1
}

# 在后台启动一个进程，并把**它自己的 pid** 记进 pid 文件。
#
# 为什么不能写成 `( cd dir && nohup cmd & echo $! > pid )`：
#   1. `&` 作用在整个 AND 列表上，bash 会额外 fork 一个**包装子 shell**，
#      于是 `$!` 记下的是包装子 shell 的 pid 而不是 cmd 的。用它去 kill，
#      只会杀掉包装层，真正的服务变成孤儿继续跑——stop.sh 就形同虚设。
#   2. 那个包装子 shell 会**继承父进程的 stdout**。如果启动脚本被管道接住
#      （`bash launch.sh | tail`，`.command` 双击也类似），管道永远不关闭，
#      外层一直挂住——现象是"命令打完了但就是退不出来"。
#
# 用 `exec` 让子 shell 被 cmd **替换**：pid 不变、包装层不存在、管道不被占住。
# stdin 接到 /dev/null，避免后台进程还连着终端。
start_bg() {
  local dir="$1" pidfile="$2" logfile="$3"; shift 3
  ( cd "$dir" && exec nohup "$@" >"$logfile" 2>&1 </dev/null ) &
  echo $! >"$pidfile"
}

# 把"已经在跑、但不是我们启动的"服务认领进来，这样 stop.sh 才能停掉它。
#
# 场景很常见：用户之前用别的脚本起过后端，或者上次启动的 pid 文件丢了。
# 不认领的话，stop.sh 会以为没东西可停，而后端一直占着端口。
adopt_running() {
  local name="$1" port="$2" pidfile="$3"
  [ -f "$pidfile" ] && return 0
  command -v lsof >/dev/null 2>&1 || return 0
  local pid
  pid="$(lsof -nP -tiTCP:"$port" -sTCP:LISTEN 2>/dev/null | head -1)"
  if [ -n "${pid:-}" ]; then
    echo "$pid" >"$pidfile"
    info "已接管的 ${name}（pid ${pid}），停止脚本会一并停掉它"
  fi
}

tail_log() {
  local file="$1"
  if [ -f "$file" ]; then
    echo "  --- $file 末尾 20 行 ---"
    tail -20 "$file" | sed 's/^/  /'
    echo "  ------------------------"
  fi
}

open_url() {
  [ "$OPEN_BROWSER" -eq 1 ] || return 0
  if command -v open >/dev/null 2>&1; then open "$1" >/dev/null 2>&1 || true
  elif command -v xdg-open >/dev/null 2>&1; then xdg-open "$1" >/dev/null 2>&1 || true
  else info "请手动在浏览器打开：$1"; fi
}

# ---------- 1. 依赖自检 ----------

info "检查运行环境…"

[ -x "$BACKEND_DIR/.venv/bin/python" ] || [ -x "$BACKEND_DIR/.venv/Scripts/python.exe" ] || fail \
"后端虚拟环境不存在。请先执行安装：
    cd src && bash install.sh"

[ -d "$FRONTEND_DIR/node_modules" ] || fail \
"前端依赖不存在。请先执行安装：
    cd src && bash install.sh"

if ! command -v ffmpeg >/dev/null 2>&1 && [ ! -x "$BACKEND_DIR/bin/ffmpeg" ]; then
  warn "未找到 ffmpeg。前面几个阶段能正常用，但**后期剪辑（视频拼接）会失败**。"
  warn "macOS 可重跑 install.sh 自动装；Linux 用系统包管理器装。"
fi

# ---------- 2. 先看清已经有什么在跑 ----------
#
# 这里刻意做成「复用优先」而不是「先杀再起」。
# 起因是一个真实场景：用户后端已经在跑、只是前端没起。
# 如果对已运行的后端报"端口被占用"，就会把人挡在门外——
# 而那明明是我们自己的服务。
#
# 所以判定分三层：
#   1. 端口空着            → 正常启动
#   2. 端口上是我们的服务  → **复用**，只补起缺的那一半
#   3. 端口被别的程序占用  → 明确报错（这时杀掉别人的进程是错的）
backend_up=0
frontend_up=0
backend_healthy && backend_up=1
port_open "$FRONTEND_PORT" && frontend_ready && frontend_up=1

if [ "$backend_up" -eq 0 ] && port_open "$BACKEND_PORT"; then
  owner="$(port_owner "$BACKEND_PORT")"
  # 端口有人在听，但 /api/health 不是我们的 → 那不是本程序
  fail "端口 ${BACKEND_PORT} 上的服务不是 Lilovideo 后端${owner:+（${owner}）}。
    请先关掉它，或换端口启动：
        LILOVIDEO_BACKEND_PORT=8010 LILOVIDEO_FRONTEND_PORT=3010 bash scripts/launch.sh"
fi

if [ "$frontend_up" -eq 0 ] && port_open "$FRONTEND_PORT"; then
  owner="$(port_owner "$FRONTEND_PORT")"
  fail "端口 ${FRONTEND_PORT} 被别的程序占用${owner:+（${owner}）}。
    请先关掉它，或换端口启动：
        LILOVIDEO_BACKEND_PORT=8010 LILOVIDEO_FRONTEND_PORT=3010 bash scripts/launch.sh"
fi

if [ "$backend_up" -eq 1 ] && [ "$frontend_up" -eq 1 ]; then
  info "服务已经在运行，直接打开浏览器。"
  info "  应用 $FRONTEND_URL"
  info "  停止 bash scripts/stop.sh"
  open_url "$FRONTEND_URL"
  exit 0
fi

# 走到这里说明至少缺一半。缺的那一半如果是我们上次启动后残留的，
# 先停掉再起，避免撞端口；已经在跑的那一半保持不动。
stop_stale() {
  local name="$1" pidfile="$2"
  [ -f "$pidfile" ] || return 0
  local pid
  pid="$(cat "$pidfile" 2>/dev/null || true)"
  if [ -n "${pid:-}" ] && kill -0 "$pid" 2>/dev/null; then
    info "停止上次残留的 ${name}（pid ${pid}）"
    kill "$pid" 2>/dev/null || true
    sleep 1
  fi
  rm -f "$pidfile"
}

if [ "$backend_up" -eq 1 ]; then
  info "后端已在运行，复用（不重启）。"
  adopt_running "后端" "$BACKEND_PORT" "$API_PID"
  # 进程在跑 ≠ 跑的是当前代码。这个坑真实发生过：改了后端源码却复用了旧进程，
  # 结果新加的接口一直 404，白排查很久。这里主动提示。
  if [ -f "$API_PID" ]; then
    newer="$(find "$BACKEND_DIR" -name '*.py' -not -path '*/.venv/*' -not -path '*/__pycache__/*' \
             -newer "$API_PID" -print -quit 2>/dev/null || true)"
    if [ -n "${newer:-}" ]; then
      warn "后端进程比源码旧（${newer#$BACKEND_DIR/} 有改动），它仍跑着旧代码。"
      warn "要加载新代码：bash scripts/stop.sh && bash scripts/launch.sh"
    fi
  fi
else
  stop_stale "后端" "$API_PID"
fi

if [ "$frontend_up" -eq 1 ]; then
  info "前端已在运行，复用（不重启）。"
  adopt_running "前端" "$FRONTEND_PORT" "$WEB_PID"
else
  stop_stale "前端" "$WEB_PID"
fi

# ---------- 3. 起后端 ----------

if [ "$backend_up" -eq 1 ]; then
  info "跳过后端启动（已在运行）"
else
info "启动后端（:${BACKEND_PORT}）…"
start_bg "$BACKEND_DIR" "$API_PID" "$API_LOG" .venv/bin/python api_server.py \
  || fail "后端启动命令失败。日志：$API_LOG"

if ! wait_for "后端就绪" 90 backend_healthy; then
  echo
  warn "后端 90 秒内没有就绪。"
  tail_log "$API_LOG"
  fail "启动失败。常见原因：config.yaml 配置有误、端口被占、依赖缺失。"
fi
info "  后端就绪 ✓"
fi

# ---------- 4. 起前端 ----------

if [ "$frontend_up" -eq 1 ]; then
  info "跳上前端启动（已在运行）"
else

if [ "$MODE" = "prod" ]; then
  if [ ! -d "$FRONTEND_DIR/.next" ]; then
    info "生产模式需要先构建（首次约几分钟）…"
    ( cd "$FRONTEND_DIR" && npm run build ) || fail "前端构建失败，请查看上面的输出。"
  fi
  info "启动前端（生产模式，:${FRONTEND_PORT}）…"
  start_bg "$FRONTEND_DIR" "$WEB_PID" "$WEB_LOG" npm run start -- --port "$FRONTEND_PORT"
else
  # 默认开发模式：不需要 build，失败点最少。
  # 用 --webpack：部分环境下 Turbopack 解析不了 lightningcss 原生模块（见 README）。
  info "启动前端（开发模式，:${FRONTEND_PORT}）…"
  start_bg "$FRONTEND_DIR" "$WEB_PID" "$WEB_LOG" npm run dev -- --webpack --port "$FRONTEND_PORT"
fi

if ! wait_for "前端就绪" 180 frontend_ready; then
  echo
  warn "前端 180 秒内没有就绪。"
  tail_log "$WEB_LOG"
  fail "启动失败。若是原生模块报错，试试：xattr -dr com.apple.quarantine $FRONTEND_DIR/node_modules"
fi
info "  前端就绪 ✓"

fi

# ---------- 5. 提示首次配置 ----------

CONFIG_FILE="$BACKEND_DIR/config.yaml"
if [ -f "$CONFIG_FILE" ]; then
  # 只检查"是否有任何一把 Key"，不读取也不回显 Key 内容
  if ! grep -qE "api_key: *['\"]?[A-Za-z0-9]" "$CONFIG_FILE"; then
    echo
    info "还没有填写任何 API Key —— 打开页面后请先到「设置」页填写，否则生成会失败。"
  fi
fi

# ---------- 6. 完成 ----------

echo
info "已启动："
info "  应用  $FRONTEND_URL"
info "  后端  $BACKEND_URL"
info "  日志  $API_LOG"
info "        $WEB_LOG"
info "  停止  bash scripts/stop.sh"
echo

open_url "$FRONTEND_URL"
