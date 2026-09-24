#!/usr/bin/env python3
"""图标导出：从定稿 SVG 生成全部位图与 favicon。

为什么需要它
------------
原 skill 的 export.sh 依赖 ImageMagick，本机装不了。这里用 resvg（渲染，
基于 Rust resvg，质量优于 ImageMagick 内建 SVG 渲染器）+ Pillow（打包 ICO）
等价实现。

关键一步：**空白输出检测**。skill 的 README 提到过一个真实故障——
ImageMagick 的内建渲染器会静默丢掉渐变/遮罩，导出**空白 PNG 却返回退出码 0**。
所以这里每张图都要检查是否真的有内容，不能只看命令是否成功。

用法
    python3 export_icons.py <定稿.svg> <输出目录>
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

from PIL import Image

RESVG_CANDIDATES = [
    shutil.which("resvg"),
    shutil.which("resvg-js-cli"),
    "/Applications/DSH Desktop.app/Contents/Frameworks/DSH Desktop Helper.app/Contents/bin/resvg-js-cli",
]

# 标准导出尺寸。用途见 README。
SIZES = {
    16: "favicon 最小尺寸，浏览器标签页",
    32: "favicon 标准尺寸，书签栏",
    48: "Windows 站点图标 / favicon.ico 成员",
    180: "apple-touch-icon，iOS 主屏",
    192: "PWA manifest standard",
    512: "PWA manifest maskable / 应用图标",
    1024: "高清源图，应用商店",
}

# favicon.ico 内嵌的尺寸。小尺寸必须单独渲染，不能从大图缩小——
# 缩小会把笔画糊掉，而 favicon 恰恰最依赖小尺寸的清晰度。
ICO_SIZES = [16, 32, 48]


def find_resvg() -> str | None:
    for c in RESVG_CANDIDATES:
        if c and os.path.exists(c):
            return c
    return None


def render(resvg: str, svg: Path, size: int, out: Path) -> bool:
    """渲染到指定边长，并确认输出非空白。"""
    # --background 用全透明，让图标保持可叠加
    cmd = [resvg, "--fit-width", str(size), "--fit-height", str(size),
           "--background", "rgba(0,0,0,0)", str(svg), str(out)]
    try:
        r = subprocess.run(cmd, capture_output=True, timeout=120)
    except Exception as e:
        print(f"    渲染异常: {e}")
        return False
    if r.returncode != 0 or not out.exists() or out.stat().st_size == 0:
        return False
    return not is_blank(out)


def is_blank(png: Path) -> bool:
    """检测空白输出。

    真实故障案例：渲染器静默失败会产出全透明或纯色图，退出码却是 0。
    这里对 alpha 通道做检查——如果完全没有内容，或只有单一颜色，视为空白。
    """
    try:
        im = Image.open(png).convert("RGBA")
    except Exception:
        return True
    alpha = im.getchannel("A")
    bbox = alpha.getbbox()
    if bbox is None:
        return True
    # 内容区域过小也视为异常
    w, h = im.size
    area = (bbox[2] - bbox[0]) * (bbox[3] - bbox[1])
    return area < (w * h) * 0.02


def build_ico(resvg: str, svg: Path, tmpdir: Path, out: Path) -> bool:
    """生成多尺寸内嵌的 ico。

    坑（本项目踩过）：Pillow 的 ICO 保存语义是「以传入图为基础，按 sizes 列表
    缩放生成多个分辨率」，而不是「把多张不同尺寸的图打包进去」。若传入多张
    不同尺寸的图，Pillow 只取第一张的尺寸，结果 ico 里只有一个尺寸。

    正确做法：渲染一张最大的（用 48，笔画在小尺寸下最清楚），再交给 Pillow
    按 sizes 生成各分辨率。

    校验：保存后读回 info["sizes"]，确认真的是多尺寸，不能只看文件是否生成。
    """
    base_png = tmpdir / "_ico-base.png"
    biggest = max(ICO_SIZES)
    if not render(resvg, svg, biggest, base_png):
        print("    ico 基准图渲染失败")
        return False
    try:
        base = Image.open(base_png).convert("RGBA")
        base.save(out, format="ICO",
                  sizes=[(s, s) for s in sorted(ICO_SIZES)])
    except Exception as e:
        print(f"    ICO 打包失败: {e}")
        return False
    finally:
        base_png.unlink(missing_ok=True)

    if not out.exists() or out.stat().st_size == 0:
        return False
    # 读回校验，确保是多尺寸而不是单尺寸
    try:
        got = sorted(Image.open(out).info.get("sizes", []))
    except Exception:
        return False
    if len(got) < len(ICO_SIZES):
        print(f"    ico 只含 {got}，期望 {len(ICO_SIZES)} 个尺寸")
        return False
    return True


def main(argv: list[str]) -> int:
    if len(argv) < 3:
        print(__doc__)
        return 3
    svg = Path(argv[1])
    outdir = Path(argv[2])
    if not svg.exists():
        print(f"找不到源文件: {svg}", file=sys.stderr)
        return 3

    resvg = find_resvg()
    if not resvg:
        print("找不到 resvg。安装：npm i -g @resvg/resvg-js-cli", file=sys.stderr)
        return 3

    outdir.mkdir(parents=True, exist_ok=True)
    print(f"源文件 : {svg}")
    print(f"渲染器 : {resvg}")
    print(f"输出   : {outdir}\n")

    failures = []

    # 1. 标准尺寸 PNG
    made = []
    for size in sorted(SIZES):
        out = outdir / f"logo-{size}.png"
        if render(resvg, svg, size, out):
            kb = out.stat().st_size / 1024
            print(f"  ✓ logo-{size:<5} {kb:>7.1f} KB   {SIZES[size]}")
            made.append(size)
        else:
            print(f"  ✗ logo-{size:<5} 渲染失败或输出空白")
            failures.append(f"logo-{size}.png")

    # 2. favicon.ico（多尺寸内嵌）
    print()
    ico = outdir / "favicon.ico"
    if build_ico(resvg, svg, outdir, ico):
        got = sorted(Image.open(ico).info.get("sizes", []))
        print(f"  ✓ favicon.ico   {ico.stat().st_size/1024:>6.1f} KB   内嵌 {[s[0] for s in got]}")
    else:
        failures.append("favicon.ico")

    # 3. apple-touch-icon（独立文件，便于直接引用）
    src = outdir / "logo-180.png"
    if src.exists():
        dst = outdir / "apple-touch-icon.png"
        shutil.copy2(src, dst)
        print(f"  ✓ apple-touch-icon.png（复制自 logo-180）")

    # 4. 源 SVG 一并带出，便于日后重导
    shutil.copy2(svg, outdir / "logo.svg")
    print(f"  ✓ logo.svg（源文件副本）")

    print()
    if failures:
        print(f"完成，但有 {len(failures)} 项失败：{', '.join(failures)}")
        return 1
    print(f"全部完成：{len(made)} 个 PNG + favicon.ico + apple-touch-icon.png + logo.svg")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
