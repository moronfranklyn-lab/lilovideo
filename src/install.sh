#!/usr/bin/env bash
# Lilovideo one-click installer
#
# 在 src/ 目录下执行：
#   bash install.sh
#
# 会在 src/backend/.venv 建立虚拟环境并安装依赖。
# 若系统 Python 低于 3.10，脚本会优先使用 uv 获取 Python 3.12。

set -u

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_DIR="$ROOT_DIR/backend"
FRONTEND_DIR="$ROOT_DIR/frontend"
PYTHON_MIN="3.10"
PYTHON_TARGET="3.12"

info()  { printf '[install] %s\n' "$1"; }
warn()  { printf '[install] WARNING: %s\n' "$1" >&2; }
fail()  { printf '[install] ERROR: %s\n' "$1" >&2; exit 1; }

# ---------- 工具检查 ----------

check_command() {
  command -v "$1" >/dev/null 2>&1
}

python_version_ok() {
  "$1" -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)" >/dev/null 2>&1
}

info "Checking prerequisites..."

check_command node  || fail "Node.js is required (>= 18). Install it, then rerun."
check_command npm   || fail "npm is required (>= 9). Install it, then rerun."

if ! check_command ffmpeg; then
  # 内置静态二进制。**不随仓库分发**（单个约 77MB，进了 git 历史无法回收），
  # 所以在这里按需下载到 src/backend/bin/，后端启动时会自动把它加进 PATH。
  #
  # 注意：不同系统的静态构建不通用。装错架构的后果是**静默坏掉**——
  # 后端会把 bin/ 前置到 PATH，于是错误的二进制盖住系统里正确的那个，
  # 直到后期剪辑阶段才报一个看不懂的错。所以这里必须先判断系统。
  FFMPEG_DIR="$REPO_DIR/src/backend/bin"
  mkdir -p "$FFMPEG_DIR"
  case "$(uname -s)" in
    Darwin)
      step "安装 ffmpeg（macOS 静态构建，约 80MB）"
      if curl -fsSL -o "$FFMPEG_DIR/ffmpeg.zip" https://evermeet.cx/ffmpeg/getrelease/zip \
         && unzip -o -q "$FFMPEG_DIR/ffmpeg.zip" -d "$FFMPEG_DIR"; then
        rm -f "$FFMPEG_DIR/ffmpeg.zip"
        xattr -dr com.apple.quarantine "$FFMPEG_DIR/ffmpeg" 2>/dev/null || true
        info "ffmpeg 已安装到 src/backend/bin/"
      else
        warn "ffmpeg 下载或解压失败，请手动放置到 $FFMPEG_DIR"
        warn "  curl -L -o $FFMPEG_DIR/ffmpeg.zip https://evermeet.cx/ffmpeg/getrelease/zip"
      fi
      ;;
    Linux)
      # 不用内置二进制：Linux 各发行版/架构差异太大，静态构建容易装错。
      # 交给系统包管理器，最省事也最不容易出问题。
      warn "未检测到 ffmpeg。请用系统包管理器安装，例如："
      warn "  Debian/Ubuntu:  sudo apt install -y ffmpeg"
      warn "  Fedora/RHEL:    sudo dnf install -y ffmpeg"
      warn "  Arch:           sudo pacman -S ffmpeg"
      warn "未安装前，后期剪辑（视频拼接）阶段会失败，其余阶段可正常使用。"
      ;;
    *)
      warn "当前系统（$(uname -s)）不在支持范围内。"
      warn "本项目依赖 bash 与 POSIX 工具，Windows 请使用 WSL，或自行安装 ffmpeg。"
      ;;
  esac
fi

# ---------- 选择 Python ----------

PYTHON_BIN=""
for candidate in python3.12 python3.11 python3.10 python3; do
  if check_command "$candidate" && python_version_ok "$candidate"; then
    PYTHON_BIN="$(command -v "$candidate")"
    break
  fi
done

if [ -z "$PYTHON_BIN" ]; then
  if check_command uv; then
    info "System Python is older than $PYTHON_MIN; using uv to fetch Python $PYTHON_TARGET"
    uv python install "$PYTHON_TARGET" || fail "uv failed to install Python $PYTHON_TARGET"
    PYTHON_BIN="$(uv python find "$PYTHON_TARGET")" || fail "Could not locate the uv-managed Python"
  else
    cat >&2 <<EOF
[install] ERROR: no Python >= $PYTHON_MIN found.

  Fix it with either:
    1. Install uv (no admin rights needed), then rerun this script:
         curl -LsSf https://astral.sh/uv/install.sh | sh
    2. Or install Python $PYTHON_TARGET from https://www.python.org/downloads/

EOF
    exit 1
  fi
fi

info "Using Python: $PYTHON_BIN ($("$PYTHON_BIN" --version 2>&1))"

# ---------- 后端依赖 ----------

info "Installing backend dependencies..."
if [ ! -d "$BACKEND_DIR/.venv" ]; then
  "$PYTHON_BIN" -m venv "$BACKEND_DIR/.venv" || fail "Could not create the backend virtual environment"
fi

VENV_PY="$BACKEND_DIR/.venv/bin/python"
[ -x "$VENV_PY" ] || VENV_PY="$BACKEND_DIR/.venv/Scripts/python.exe"

"$VENV_PY" -m pip install --upgrade pip >/dev/null 2>&1 || warn "Could not upgrade pip; continuing"

if command -v uv >/dev/null 2>&1; then
  (cd "$BACKEND_DIR" && uv pip install --python "$VENV_PY" -r requirements.txt) || {
    warn "uv install failed; falling back to pip"
    "$VENV_PY" -m pip install -r "$BACKEND_DIR/requirements.txt" || fail "Backend dependency install failed"
  }
else
  "$VENV_PY" -m pip install -r "$BACKEND_DIR/requirements.txt" || fail "Backend dependency install failed"
fi

if [ ! -f "$BACKEND_DIR/config.yaml" ]; then
  cp "$BACKEND_DIR/config.yaml.example" "$BACKEND_DIR/config.yaml"
  info "Created backend/config.yaml — fill in your API keys before generating videos."
fi

# ---------- 前端依赖 ----------

info "Installing frontend dependencies..."
(cd "$FRONTEND_DIR" && npm install) || fail "Frontend dependency install failed"

# ---------- 完成 ----------

cat <<EOF

[install] Lilovideo installation complete.

Next steps:
  1. Edit src/backend/config.yaml and fill in the API keys for the models you use.
  2. Start the backend:
       cd src/backend && .venv/bin/python api_server.py
  3. Start the frontend (new terminal):
       cd src/frontend && npm run dev -- --webpack

  Backend: http://localhost:8000
  Frontend: http://localhost:3000

EOF
