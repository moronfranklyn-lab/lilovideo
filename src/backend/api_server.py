# -*- coding: utf-8 -*-
"""
Compatibility entrypoint for the Lilovideo FastAPI server.
"""

import os
import sys

_backend_dir = os.path.dirname(os.path.abspath(__file__))
if _backend_dir not in sys.path:
    sys.path.insert(0, _backend_dir)

# 项目内置 ffmpeg：优先于系统 PATH，供 shutil.which("ffmpeg") 找到
# （macOS 本机未装 ffmpeg 时，使用 src/backend/bin/ffmpeg 静态二进制）
_bin_dir = os.path.join(_backend_dir, "bin")
if os.path.isdir(_bin_dir):
    os.environ["PATH"] = _bin_dir + os.pathsep + os.environ.get("PATH", "")

import uvicorn

from api.app import app
from config import settings


def main():
    uvicorn.run(app, host=settings.HOST, port=settings.PORT, access_log=settings.ACCESS_LOG)


if __name__ == "__main__":
    main()
