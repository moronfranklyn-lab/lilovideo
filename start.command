#!/usr/bin/env bash
# macOS 双击启动入口。
#
# 为什么需要这个文件：Finder 里双击 .command 会用终端执行它，
# 这是不装 Electron 也能做到"双击即用"的最省办法。
#
# 双击后终端窗口会一直开着——这是故意的：启动信息与后续日志都在这里，
# 出错时用户能直接看到原因，而不是"双击了没反应"。
set -u
cd "$(dirname "$0")"

echo "Lilovideo 启动中…（这个窗口请保持打开，关闭窗口即停止服务）"
echo

bash scripts/launch.sh
code=$?

echo
if [ "$code" -ne 0 ]; then
  echo "启动失败。请把上面的错误信息发给开发者，或先手动执行："
  echo "    cd src && bash install.sh"
else
  echo "服务已启动。要停止服务，按 Ctrl+C 或关闭本窗口，也可以运行："
  echo "    bash scripts/stop.sh"
fi
echo
# 保持窗口，让用户看清信息；按回车才关闭
read -r -p "按回车键关闭此窗口…" _ || true
