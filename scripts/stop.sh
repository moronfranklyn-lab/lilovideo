#!/usr/bin/env bash
# Lilovideo 停止脚本
#
# 只停本程序启动（或接管）的进程，按 pid 文件定位，不会误杀别的程序。
set -u

LOG_DIR="$(printf '%s' "${TMPDIR:-/tmp}" | sed 's:/*$::')/lilovideo"
info() { printf '[Lilovideo] %s\n' "$1"; }

# 先递归停子进程，再停自己。
#
# 为什么需要：`npm run dev` 自己还会 fork 出 `next dev` → `next-server`。
# 只 kill npm 的话，真正在服务的 next-server 会变成孤儿继续占着端口，
# 用户会看到"停止脚本说停成功了，但页面还能打开"。
kill_tree() {
  local pid="$1" child
  if command -v pgrep >/dev/null 2>&1; then
    for child in $(pgrep -P "$pid" 2>/dev/null); do
      kill_tree "$child"
    done
  fi
  kill "$pid" 2>/dev/null || true
}

stopped=0
for name in backend frontend; do
  pidfile="$LOG_DIR/$name.pid"
  [ -f "$pidfile" ] || continue
  pid="$(cat "$pidfile" 2>/dev/null || true)"
  [ -n "${pid:-}" ] || { rm -f "$pidfile"; continue; }

  if kill -0 "$pid" 2>/dev/null; then
    kill_tree "$pid"
    # 给进程收尾时间。后端是 uvicorn：它会等现有连接结束，
    # 而且 orchestrator 的后台线程不是 daemon，线程没结束进程就不退。
    # 10 秒比 5 秒稳，也不至于让用户等太久。
    for _ in $(seq 1 20); do
      kill -0 "$pid" 2>/dev/null || break
      sleep 0.5
    done
    if kill -0 "$pid" 2>/dev/null; then
      info "${name}（pid ${pid}）未响应，强制结束"
      kill -9 "$pid" 2>/dev/null || true
    else
      info "${name}（pid ${pid}）已停止"
    fi
    stopped=$((stopped + 1))
  else
    info "${name}（pid ${pid}）已经不在运行"
  fi
  rm -f "$pidfile"
done

# 兜底：上面靠 pid 文件。若 pid 文件丢了（比如系统清理过临时目录），
# 再按命令行特征扫一遍本项目残留的 node 服务进程。
if command -v pkill >/dev/null 2>&1; then
  pkill -f "next dev --webpack --port" 2>/dev/null || true
  pkill -f "next start --port" 2>/dev/null || true
fi

if [ "$stopped" -eq 0 ]; then
  info "没有找到本程序启动的进程（可能已经停了）"
else
  info "已停止 ${stopped} 个服务"
fi
