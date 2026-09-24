#!/usr/bin/env bash
# Lilovideo 后端启动脚本
#
# 用法：bash start_backend.sh
#
# 这个脚本会把项目自带的 ffmpeg 加入 PATH，再启动后端。
# 之所以需要，是因为后期剪辑阶段直接调用 ffmpeg 命令，
# 而 ffmpeg 装在项目内的 tools/ffmpeg/，不在系统路径里。

set -e

# 仓库根目录（本脚本位于 src/ 下）
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKEND_DIR="$REPO_DIR/src/backend"
WORKSPACE_DIR="$(cd "$REPO_DIR/.." && pwd)"

# 项目自带工具链（刻意装在外接磁盘，不占用内置磁盘）
FFMPEG_DIR="$WORKSPACE_DIR/tools/ffmpeg"
UV_DIR="$WORKSPACE_DIR/tools/uv"

# 把项目内工具加入 PATH（放在最前，优先于系统版本）
if [ -x "$FFMPEG_DIR/ffmpeg" ]; then
  export PATH="$FFMPEG_DIR:$PATH"
  echo "[start] ffmpeg: $("$FFMPEG_DIR/ffmpeg" -version 2>/dev/null | head -1)"
else
  echo "[start] 警告：未找到 $FFMPEG_DIR/ffmpeg"
  echo "        后期剪辑阶段会失败。安装方法："
  echo "        mkdir -p $FFMPEG_DIR && cd $FFMPEG_DIR"
  echo "        curl -sL -o ffmpeg.zip https://evermeet.cx/ffmpeg/getrelease/zip && unzip -o ffmpeg.zip"
  echo "        xattr -dr com.apple.quarantine ."
fi

if [ -d "$UV_DIR" ]; then
  export PATH="$UV_DIR:$PATH"
fi

# 检查虚拟环境
if [ ! -x "$BACKEND_DIR/.venv/bin/python" ]; then
  echo "[start] 错误：未找到后端虚拟环境 $BACKEND_DIR/.venv"
  echo "        请先运行：cd src && bash install.sh"
  exit 1
fi

# 检查密钥是否已配置（只看 api_key 行是否为占位符，不看注释）
if grep -E "^[[:space:]]*api_key:[[:space:]]*PASTE_YOUR_KEY_HERE" "$BACKEND_DIR/config.yaml" >/dev/null 2>&1; then
  echo "[start] 错误：config.yaml 里的 api_key 还是占位符"
  echo "        请填入 dashscope 和 ark 的 API Key，详见 docs/模型密钥填写说明.md"
  exit 1
fi

echo "[start] 后端目录: $BACKEND_DIR"
echo "[start] 启动服务: http://localhost:8000"
echo

cd "$BACKEND_DIR"
exec .venv/bin/python api_server.py
