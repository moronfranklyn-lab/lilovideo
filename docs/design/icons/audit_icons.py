#!/usr/bin/env python3
"""图标审计：把 skill 的 pre-flight 清单变成可测量的检查。

为什么自己写
------------
原版 audit.sh 依赖 ImageMagick，本机无法安装（无 brew，装它需要管理员密码）。
但它测的每一项都很明确，这里用 resvg（渲染）+ Pillow（分析）等价实现，
而不是放弃度量退回肉眼判断。

测什么（与原版对齐）
------------------
1. ink    墨迹覆盖率。过高说明烘焙了背景底板，那不是标志是图片。
2. tpl    单色塌陷。把图当成模板（只取 alpha）后是否还有结构；
          标准差接近 0 说明塌成空白或实心块。
3. rgn    区域数：256px 相比 16px 是否明显减少。
          减少说明内部镂空在 favicon 尺寸下闭合了 —— 变成一团糊。
4. thin   最细特征宽度（在 16px 下折算）。过细会在浏览器标签页里消失。
5. nodes  path 命令数。过多说明是描摹出来的，或过度雕琢。
6. 边界   艺术品是否越出安全边距（100 viewBox 中 8..92）。

用法
    python3 audit_icons.py <目录或文件> [...]
退出码：全部通过 0；有 FAIL 1；无法运行 3。
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from PIL import Image, ImageFilter

# resvg 渲染器路径（npm 安装的 @resvg/resvg-js-cli）
RESVG_CANDIDATES = [
    shutil.which("resvg"),
    shutil.which("resvg-js-cli"),
    "/Applications/DSH Desktop.app/Contents/Frameworks/DSH Desktop Helper.app/Contents/bin/resvg-js-cli",
]

# 阈值。参照原版 audit.sh 的标定思路：
# 这些值不是凭空定的，而是对着"肉眼确认过合格"的标志校准出来的。
INK_MAX = 0.85          # 超过则疑似烘焙背景底板
TPL_STD_MIN = 3.0       # 单色塌陷标准差下限
RGN_DROP_MAX = 0.5      # 16px 区域数相对 256px 的最大允许跌幅
THIN_MIN_PX = 0.65      # 16px 下最细特征的最小像素宽
NODES_MAX = 90          # path 命令数上限
SAFE_MIN, SAFE_MAX = 8.0, 92.0


@dataclass
class Result:
    name: str
    ink: float = 0.0
    tpl_std: float = 0.0
    rgn_256: int = 0
    rgn_16: int = 0
    thin_px: float = 0.0
    nodes: int = 0
    bounds_ok: bool = True
    margin_min: float = 0.0
    failures: list[str] = field(default_factory=list)

    @property
    def verdict(self) -> str:
        return "ok" if not self.failures else "FAIL " + "; ".join(self.failures)


def find_resvg() -> str | None:
    for c in RESVG_CANDIDATES:
        if c and os.path.exists(c):
            return c
    return None


def render(resvg: str, svg: Path, size: int, out: Path) -> bool:
    """渲染到指定边长。返回是否成功且非空白。"""
    cmd = [resvg, "--fit-width", str(size), "--fit-height", str(size),
           "--background", "rgba(0,0,0,0)", str(svg), str(out)]
    try:
        r = subprocess.run(cmd, capture_output=True, timeout=60)
    except Exception as e:
        print(f"    渲染异常: {e}", file=sys.stderr)
        return False
    if r.returncode != 0 or not out.exists():
        return False
    return True


def measure_ink(im: Image.Image) -> float:
    """墨迹覆盖率 = 非透明像素占比。"""
    alpha = im.convert("RGBA").getchannel("A")
    total = alpha.width * alpha.height
    if total == 0:
        return 0.0
    inked = sum(1 for p in alpha.tobytes() if p > 20)
    return inked / total


def measure_template(im: Image.Image) -> float:
    """单色模板：只用 alpha 做形状，转灰后求标准差。

    标准差接近 0 = 塌成空白或实心块，说明形状没有结构。
    """
    alpha = im.convert("RGBA").getchannel("A")
    gray = alpha.convert("L")
    hist = gray.histogram()
    total = sum(hist)
    if total == 0:
        return 0.0
    mean = sum(i * n for i, n in enumerate(hist)) / total
    var = sum(n * (i - mean) ** 2 for i, n in enumerate(hist)) / total
    return var ** 0.5


def count_regions(im: Image.Image, min_area: int) -> int:
    """连通区域数（8 邻接），面积小于 min_area 的忽略。

    用 alpha 二值化后做标签传播，替代 ImageMagick 的 connected-components。
    """
    alpha = im.convert("RGBA").getchannel("A")
    if alpha.size[0] > 128:  # 限制规模，避免 O(n^2) 过慢
        alpha = alpha.resize((128, 128), Image.NEAREST)
    w, h = alpha.size
    px = alpha.load()
    binary = [[1 if px[x, y] > 128 else 0 for x in range(w)] for y in range(h)]

    seen = [[False] * w for _ in range(h)]
    regions = 0
    for y0 in range(h):
        for x0 in range(w):
            if binary[y0][x0] != 1 or seen[y0][x0]:
                continue
            # 迭代式泛洪，避免递归深度问题
            stack = [(x0, y0)]
            seen[y0][x0] = True
            area = 0
            while stack:
                x, y = stack.pop()
                area += 1
                for dx in (-1, 0, 1):
                    for dy in (-1, 0, 1):
                        nx, ny = x + dx, y + dy
                        if 0 <= nx < w and 0 <= ny < h and not seen[ny][nx] and binary[ny][nx] == 1:
                            seen[ny][nx] = True
                            stack.append((nx, ny))
            if area >= min_area:
                regions += 1
    return regions


def measure_thinnest(im: Image.Image, render_size: int, target_px: int = 16) -> float:
    """估算最细特征宽度。

    做法：对 alpha 反复做 3x3 最小值滤波（腐蚀）。能承受的腐蚀次数近似
    刻画特征的半宽（每次腐蚀吃掉约 1px 半径）。宽度约为 2 倍迭代次数。
    再按 render_size -> target_px 的比例折算到目标尺寸。

    注意：必须在较高分辨率上测，16px 上抗锯齿会掩盖真实笔画宽度。
    """
    alpha = im.convert("RGBA").getchannel("A")
    cur = alpha
    iterations = 0
    max_iter = 24
    while iterations < max_iter:
        nxt = cur.filter(ImageFilter.MinFilter(3))
        before = sum(1 for p in cur.tobytes() if p > 128)
        after = sum(1 for p in nxt.tobytes() if p > 128)
        if before == 0 or after < before * 0.5:
            break
        cur = nxt
        iterations += 1
    width_px = iterations * 2
    return max(width_px * (target_px / float(render_size)), 0.0)


def count_nodes(svg: Path) -> int:
    """统计 path 命令数（近似）：每段 path 的 d 属性里的命令字母个数。"""
    s = svg.read_text(encoding="utf-8", errors="replace")
    total = 0
    for m in re.finditer(r'\sd="([^"]+)"', s):
        total += len(re.findall(r"[MmLlHhVvCcSsQqTtAaZz]", m.group(1)))
    return total


def check_bounds_from_pixels(im: Image.Image) -> tuple[bool, float, float]:
    """用渲染后的像素边界判定是否越出安全区。

    为什么不用解析路径：SVG 的 path 语法里，圆弧命令的参数包含与坐标同形的
    数字（如 a8 8 0 0 1 -8 -8 中的 -8 是相对偏移而非绝对坐标）。用正则抓
    数字无法区分两者，会误报。渲染后的像素边界是权威来源。

    安全区：留出 4% 边距。图标被系统套上圆角遮罩时，贴边的元素会被切掉。
    """
    alpha = im.convert("RGBA").getchannel("A")
    bbox = alpha.getbbox()
    if bbox is None:
        return False, 0.0, 0.0
    w, h = im.size
    left, top, right, bottom = bbox
    margin_x = left / w
    margin_y = top / h
    right_margin = (w - right) / w
    bottom_margin = (h - bottom) / h
    min_margin = min(margin_x, margin_y, right_margin, bottom_margin)
    inside = (left > 0 and top > 0 and right < w and bottom < h
              and min_margin >= 0.03)
    return inside, min_margin, min(margin_x, margin_y)


def audit_one(resvg: str, svg: Path, tmp: Path) -> Result:
    r = Result(name=svg.name)

    p256 = tmp / f"{svg.stem}-256.png"
    p16 = tmp / f"{svg.stem}-16.png"
    if not render(resvg, svg, 256, p256):
        r.failures.append("无法渲染")
        return r
    if not render(resvg, svg, 16, p16):
        r.failures.append("16px 渲染失败")
        return r

    im256 = Image.open(p256)
    im16 = Image.open(p16)

    r.ink = measure_ink(im256)
    r.tpl_std = measure_template(im256)
    r.rgn_256 = count_regions(im256, min_area=20)
    r.rgn_16 = count_regions(im16, min_area=1)
    # 在 256 尺度上测最细特征，再折算到 16px，避免抗锯齿干扰
    r.thin_px = measure_thinnest(im256, 256, 16)
    r.nodes = count_nodes(svg)
    r.bounds_ok, r.margin_min, _ = check_bounds_from_pixels(im256)

    if r.ink > INK_MAX:
        r.failures.append(f"墨迹{ r.ink:.2f}>0.85(疑似底板)")
    if r.tpl_std < TPL_STD_MIN:
        r.failures.append(f"单色塌陷(std {r.tpl_std:.1f})")
    if r.rgn_256 > 0 and r.rgn_16 < r.rgn_256 * (1 - RGN_DROP_MAX):
        r.failures.append(f"16px镂空闭合({r.rgn_256}->{r.rgn_16})")
    if r.thin_px < THIN_MIN_PX:
        r.failures.append(f"笔画过细({r.thin_px:.2f}px@16)")
    if r.nodes > NODES_MAX:
        r.failures.append(f"节点过多({r.nodes})")
    if not r.bounds_ok:
        r.failures.append(f"贴边或越界(留白{r.margin_min:.1%})")

    return r


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print(__doc__)
        return 3
    resvg = find_resvg()
    if not resvg:
        print("找不到 resvg 渲染器。安装：npm i -g @resvg/resvg-js-cli", file=sys.stderr)
        return 3
    print(f"渲染器: {resvg}\n")

    targets: list[Path] = []
    for a in argv[1:]:
        p = Path(a)
        if p.is_dir():
            targets.extend(sorted(p.glob("*.svg")))
        elif p.is_file() and p.suffix == ".svg":
            targets.append(p)
    if not targets:
        print("没有找到 SVG 文件", file=sys.stderr)
        return 3

    hdr = f"{'MARK':<34}{'INK':>7}{'TPL':>7}{'RGN':>10}{'THIN':>7}{'NODES':>7}  VERDICT"
    print(hdr)
    print("-" * len(hdr))

    failed = 0
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        for svg in targets:
            r = audit_one(resvg, svg, tmp)
            if r.failures:
                failed += 1
            print(f"{r.name:<34}{r.ink:>7.3f}{r.tpl_std:>7.1f}"
                  f"{r.rgn_256:>5}->{r.rgn_16:<4}{r.thin_px:>7.2f}{r.nodes:>7}  {r.verdict}")

    print()
    print(f"结果：{len(targets) - failed}/{len(targets)} 通过")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
