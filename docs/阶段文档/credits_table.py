#!/usr/bin/env python3
"""千问 / 豆包 视频模型积分换算表生成器。

为什么要有这个脚本
------------------
"把所有视频模型都加上去换算积分"这件事，一旦手写就会出错，而且是**静默**出错：

- 一个模型有 1~4 个档位（480P / 720P 无声 / 720P 带音 / 1080P 带音），
  漏掉一档就是用户能选到没标价的模型
- 两个平台计费口径完全不同：通义按**秒**，豆包按 **tokens**
- 积分数还依赖 K，K 一改全表都要变

所以价格来自 `models/pricing.py`（运行时用的同一份注册表），
积分数由公式现算，本脚本只负责排版。

一条重要的分工
--------------
- **价格**：不在这里写，全部读 `src/backend/models/pricing.py`。
  那里每条都带来源与核实状态。本脚本若自己写一份价格，
  两边迟早不一致——这正是本项目已经踩过的坑。
- **积分**：公式从 `pricing_calc.py` 导入，不复制。
  公式复制两份的后果是改了一处忘了另一处。

用法
    python3 credits_table.py                # 打印到 stdout
    python3 credits_table.py --write        # 写入 积分换算表.md
    python3 credits_table.py --check        # 校验磁盘上的 md 是否是最新的（CI 用）
    python3 credits_table.py --k 1.4 --seconds 5
    python3 credits_table.py --check-ark    # 重新查询方舟可用模型并与快照比对
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.request

# ── 让脚本能 import 后端的定价注册表 ────────────────────────────────────
_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.dirname(os.path.dirname(_HERE))          # lilovideo/
_BACKEND = os.path.join(_REPO, "src", "backend")
if _BACKEND not in sys.path:
    sys.path.insert(0, _BACKEND)

from models.pricing import PRICING  # noqa: E402
from models.video_catalog import VideoSku, list_video_skus  # noqa: E402

from pricing_calc import (  # noqa: E402
    CREDITS_PER_YUAN_COST,
    YUAN_PER_CREDIT_UNIT,
    margin,
    yuan_per_credit,
)

OUT_NAME = "积分换算表.md"
GENERATED_DATE = "2026-09-23"

# ── 本产品只卖"参考图 → 视频"这条主流程用得上的模型 ──────────────────────
#
# 通义百炼上视频生成有 40+ 个条目（含 s2v 语音驱动、animate 换脸、
# videoedit 视频编辑、liveportrait 等专用模型，以及 kling/vidu/pixverse
# 等第三方托管模型）。那些不是"生视频"，不进这张表。
#
# 这里只排除两类：
#  1. 非生成类（编辑 / 换脸 / 语音驱动 / 口型）
#  2. 本产品不接的第三方托管模型
# 保留 i2v（图生）、r2v（参考生）、t2v（文生）三类生成模型。
EXCLUDED_NOTE = (
    "百炼上另有 s2v（语音驱动）、animate（换脸）、videoedit（视频编辑）、"
    "liveportrait 等专用模型，以及 kling / vidu / pixverse / MiniMax 等第三方托管模型。"
    "它们不是「生视频」，本产品不接，故不入表。"
)

# ── 推荐档位：这是**产品决定**，不是算出来的 ────────────────────────────
#
# 价格和积分都由脚本算；"哪一档承担什么角色"是产品判断，必须人写。
# 五个角色对应《组合计价.md》的五档。
TIER_ROLES: list[tuple[str, str, str]] = [
    ("特价", "wan2.6-i2v-flash", "720P 无声", "拉新引流。全表最低成本，样片模式默认用它。"),
    ("入门", "wan2.6-i2v-flash", "720P 带音", "能出声的最低档。口播、对白类内容起步就用这档。"),
    ("标准", "wan2.7-i2v", "720P", "通义 2.7 代表演能力，成本确定，是「不确定题材」的安全选择。"),
    ("高质", "doubao-seedance-2-0-fast-260128", "720P", "Seedance 快档，角色一致性与画质明显上一台阶。"),
    ("高端", "doubao-seedance-2-5-260628", "720P", "当前最强档，用于关键镜头；也是唯一能出 1080P 的档（262 积分）。"),
]

# ── 方舟可用模型快照 ───────────────────────────────────────────────────
#
# 来源：`GET https://ark.cn-beijing.volces.com/api/v3/models`
# （Bearer 用 config.yaml 里的 ark.api_key）。查询日期 2026-09-23，
# 返回 135 个模型，其中视频相关 12 个，全部列在下面。
#
# 为什么不实时查：生成文档要可复现。网络一抖文档就变，等于没有基线。
# 想刷新就用 `--check-ark`，它会重新查一遍并与这份快照比对。
ARK_VIDEO_SNAPSHOT: list[tuple[str, str, str]] = [
    # (模型 ID, 状态, 任务类型)
    ("doubao-seedance-2-5-260628", "在役", "多模态→视频 / 视频延长 / 视频编辑"),
    ("doubao-seedance-2-0-260128", "在役", "多模态→视频 / 视频延长 / 视频编辑"),
    ("doubao-seedance-2-0-fast-260128", "在役", "多模态→视频 / 视频延长 / 视频编辑"),
    ("doubao-seedance-2-0-mini-260615", "在役", "多模态→视频 / 视频编辑 / 视频延长"),
    ("doubao-seedance-1-0-pro-250528", "在役（老一代）", "图生视频 / 文生视频"),
    ("doubao-seedance-1-0-pro-fast-251015", "在役（老一代）", "图生视频 / 文生视频"),
    ("doubao-seedance-1-5-pro-251215", "即将下线", "文/图→带音视频"),
    ("doubao-seedance-1-0-lite-i2v-250428", "即将下线", "图生视频"),
    ("doubao-seedance-1-0-lite-t2v-250428", "即将下线", "文生视频"),
    ("wan2-1-14b-i2v-250225", "已下线", "—"),
    ("wan2-1-14b-t2v-250225", "已下线", "—"),
    ("wan2-1-14b-flf2v-250417", "已下线", "—"),
]

# 方舟上这些视频模型**没有**登记定价，原因逐条写清楚，不含糊。
ARK_UNPRICED_REASON = {
    "doubao-seedance-1-0-pro-250528": "老一代（2025-05），官方中文价目页抓不到，单价未取到",
    "doubao-seedance-1-0-pro-fast-251015": "同上；字节官方推荐用它替代已下线的 Lite",
    "doubao-seedance-1-5-pro-251215": "标记为即将下线，不推荐新品接入",
    "doubao-seedance-1-0-lite-i2v-250428": "标记为即将下线",
    "doubao-seedance-1-0-lite-t2v-250428": "标记为即将下线",
}


# 可售档位的枚举已挪到后端 `models/video_catalog.py`，这里只做一层包装。
#
# 为什么要挪：原先"接口能报的价"和"文档里写的价"是两套代码展开的，
# 迟早对不上。现在 API 与本脚本共用同一个 `list_video_skus()`，
# 文档里显示什么档位、什么积分，接口就返回什么。
#
# 保留这个别名是为了让脚本内部读起来短一些。
Sku = VideoSku


def build_skus(k: float, seconds: float) -> list[Sku]:
    """展开全部可售档位（委托给后端目录）。"""
    return list_video_skus(k=k, seconds=seconds)


def _money(x: float) -> str:
    return f"¥{x:,.2f}"


def render(k: float, seconds: float) -> str:
    """生成整份 markdown。"""
    skus = build_skus(k, seconds)
    ypc = yuan_per_credit(k)
    designed = margin(k)
    cheapest = min(skus, key=lambda s: s.cost)
    priciest = max(skus, key=lambda s: s.cost)
    span = priciest.cost / cheapest.cost

    by_model: dict[str, list[Sku]] = {}
    for s in skus:
        by_model.setdefault(s.model_id, []).append(s)

    out: list[str] = []
    w = out.append

    w("# 千问 / 豆包 视频模型积分换算表")
    w("")
    w("| 项目 | 内容 |")
    w("| --- | --- |")
    w("| 阶段 | 3 产品能力（计费模型） |")
    w("| 状态 | 定价已核实到官方页面；积分规则定稿；**未接真实支付** |")
    w(f"| 生成方式 | 由 `credits_table.py` 生成，**不手写**；生成日期 {GENERATED_DATE} |")
    w(f"| 价格来源 | `src/backend/models/pricing.py`（运行时同一份注册表） |")
    w(f"| 换算基准 | `积分 = 成本(元) × {CREDITS_PER_YUAN_COST} × K`，K = {k}，1 积分 = ¥{ypc:.2f} |")
    w(f"| 片段时长 | 本表按 **{seconds:g} 秒**一个片段计算 |")
    w("")
    w("> 重新生成：`python3 credits_table.py --write`")
    w("> 校验文档是否过期：`python3 credits_table.py --check`（过期则退出码非 0）")
    w("")
    w("---")
    w("")

    # ── 1 结论 ────────────────────────────────────────────────────────
    w("## 1. 一页结论")
    w("")
    w(f"- 可售档位 **{len(skus)} 个**（{len(by_model)} 个模型 × 各自的分辨率/音轨档）")
    w(f"- 最便宜：**{cheapest.display} {cheapest.label}** "
      f"→ {cheapest.credits} 积分（成本 {_money(cheapest.cost)}，{_money(cheapest.per_second)}/秒）")
    w(f"- 最贵：**{priciest.display} {priciest.label}** "
      f"→ {priciest.credits} 积分（成本 {_money(priciest.cost)}，{_money(priciest.per_second)}/秒）")
    w(f"- 首尾成本差 **{span:.1f} 倍**，积分差 "
      f"**{priciest.credits / max(cheapest.credits, 1):.1f} 倍**")
    w(f"- 设计毛利 **{designed:.1%}**（K = {k}）")
    w("")
    w(f"**一句话**：同样一个 {seconds:g} 秒镜头，用户最少花 {cheapest.credits} 积分、"
      f"最多花 {priciest.credits} 积分。**给用户选，但必须给指导**——"
      f"单纯把 {len(skus)} 个档位摊开等于把决策成本丢给用户。")
    w("")
    w("---")
    w("")

    # ── 2 换算规则 ────────────────────────────────────────────────────
    w("## 2. 换算规则（两个平台口径不同，这是全表的关键）")
    w("")
    w("```")
    w(f"积分消耗 = 成本(元) × {CREDITS_PER_YUAN_COST} × K        K = {k}")
    w(f"1 积分售价 = K × {YUAN_PER_CREDIT_UNIT} 元 = ¥{ypc:.2f}")
    w("```")
    w("")
    w("| 平台 | 计费方式 | 成本可预测性 | 报价依据 |")
    w("| --- | --- | --- | --- |")
    w("| 千问·通义（百炼） | 按**秒** | **完全确定** | 官方价目表直读，单价 × 秒数 |")
    w("| 豆包·Seedance（方舟） | 按 **tokens** | 随任务浮动 | 官方费率 × **实测** tokens 量 |")
    w("")
    w("**这个差别不是细节，是产品卖点。**")
    w("Seedance 的 tokens 量随任务类型浮动——同一个模型、同样 720P，")
    w("「含视频输入」的任务（视频编辑 / 视频延长）用量约为图生视频的 2 倍。")
    w("（这一条是二手口径，本项目只实测了图生视频那一侧，未实测含视频输入的任务；")
    w("但足以说明成本会浮动。）")
    w("通义按秒定价则一分不差。所以：**预算敏感、需要给用户报死价的场景，用通义；")
    w("画质优先、接受浮动的场景，用 Seedance。**")
    w("")
    w("---")
    w("")

    # ── 3 通义 ────────────────────────────────────────────────────────
    w("## 3. 千问 / 通义 视频模型（按秒计费）")
    w("")
    w("华北2（北京）区域官方原价。海外区域另有价格，本项目不部署海外，不登记。")
    w("")
    w(f"| 模型 | 类型 | 档位 | 元/秒 | {seconds:g} 秒成本 | **积分** | 用户实付 | 核实 |")
    w("| --- | --- | --- | ---: | ---: | ---: | ---: | :---: |")
    for model_id, group in by_model.items():
        if group[0].vendor != "千问·通义":
            continue
        for i, s in enumerate(group):
            name = s.display if i == 0 else ""
            kind = s.kind if i == 0 else ""
            w(f"| {name} | {kind} | {s.label} | {_money(s.per_second)} | {_money(s.cost)} "
              f"| **{s.credits}** | {_money(s.credits * ypc)} | {'✅' if s.verified else '⚠️'} |")
    w("")
    w("---")
    w("")

    # ── 4 豆包 ────────────────────────────────────────────────────────
    w("## 4. 豆包 / Seedance 视频模型（按 tokens 计费）")
    w("")
    w("**官方计费公式**（方舟控制台价目页原文）：")
    w("")
    w("```")
    w("不含视频输入：tokens = 宽 × 高 × 帧率 × 输出时长 ÷ 1024")
    w("包含视频输入：tokens = 宽 × 高 × 帧率 × (输入时长 + 输出时长) ÷ 1024")
    w("")
    w("帧率 = 24")
    w("480P  854 × 480     720P  1280 × 720     1080P  1920 × 1080")
    w("```")
    w("")
    w("分辨率与帧率由价目页的 **6 行示例**反推确认（3 档 × 2 种时长），全部精确吻合，"
      "所以这不是猜的。")
    w("")
    w("> **「含视频输入」单价更低，却往往总价更高**：它按 (输入+输出) 总时长计费。")
    w("> 例如 720P 输入 10 秒 + 输出 10 秒 = 432,000 tokens，是普通 5 秒生成的 4 倍。")
    w("")
    w("> 实测与官方公式有偏差（720P +0.83%、480P +5.41%，实测偏高），"
      "已如实记录在《积分与会员模型.md》§2.5。**成本记账走 API 真实用量，不受影响**；"
      "本表只用于报价与定价。")
    w("")
    w(f"| 模型 | 分辨率 | 元/百万 tokens | {seconds:g} 秒 tokens | 元/秒 "
      f"| {seconds:g} 秒成本 | **积分** | 用户实付 | 核实 |")
    w("| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | :---: |")
    for model_id, group in by_model.items():
        if group[0].vendor != "豆包·Seedance":
            continue
        for s in group:
            w(f"| {s.display} | {s.label} | {s.per_million_tokens:g} | {s.token_count:,.1f} "
              f"| {_money(s.per_second)} | {_money(s.cost)} "
              f"| **{s.credits}** | {_money(s.credits * ypc)} | {'✅' if s.verified else '⚠️'} |")
    w("")
    if any(not sk.verified for sk in skus):
        w("> ⚠️ = 定价未完全核实，上线前需核对（见第 8 节）。")
    else:
        w("> 全部档位的定价均已核实。豆包侧费率来自方舟控制台价目页，"
          "通义侧直读官方模型页。")
    w("")
    w("---")
    w("")

    # ── 5 合并阶梯 ────────────────────────────────────────────────────
    w("## 5. 合并后的完整价目阶梯（按每秒成本升序）")
    w("")
    w("**这张表就是用户真正面对的菜单。** 一屏看完 "
      f"{len(skus)} 个档位谁贵谁便宜。")
    w("")
    w("| # | 模型 | 档位 | 元/秒 | **积分** | 用户实付 | 平台绝对毛利 |")
    w("| ---: | --- | --- | ---: | ---: | ---: | ---: |")
    for i, s in enumerate(sorted(skus, key=lambda x: (x.cost, x.model_id)), 1):
        revenue = s.credits * ypc
        w(f"| {i} | {s.display} | {s.label} | {_money(s.per_second)} | **{s.credits}** "
          f"| {_money(revenue)} | {_money(revenue - s.cost)} |")
    w("")
    w("### 一个反直觉但必须知道的事实")
    w("")
    w("**所有档位的毛利率相同（K 相同），所以绝对利润随成本线性增长。**")
    w("卖 1 个高端镜头的利润 ≈ 卖 "
      f"{priciest.credits / max(cheapest.credits, 1):.0f} 个特价镜头。")
    w("")
    w("两条推论：")
    w("")
    w("1. **高端档要推，不是要藏。** 它既不伤毛利，又是画质的来源。")
    w("2. **特价档必须限量。** 全部用量走特价档时，平台每片段只赚 "
      f"{_money(cheapest.credits * ypc - cheapest.cost)}。"
      "特价的作用是拉新，不是承接全部用量。")
    w("")
    w("---")
    w("")

    # ── 6 推荐五档 ────────────────────────────────────────────────────
    w("## 6. 推荐五档（角色是产品决定，数字是算出来的）")
    w("")
    w(f"| 档位 | 模型 | 档位 | {seconds:g} 秒成本 | **积分** | 用户实付 | 为什么是它 |")
    w("| --- | --- | --- | ---: | ---: | ---: | --- |")
    for role, model_id, label, reason in TIER_ROLES:
        match = next((s for s in skus if s.model_id == model_id and s.label == label), None)
        if match is None:
            w(f"| **{role}** | {_display_name(model_id)} | {label} | — | — | — | 定价缺失，待补 |")
            continue
        w(f"| **{role}** | {match.display} | {match.label} | {_money(match.cost)} "
          f"| **{match.credits}** | {_money(match.credits * ypc)} | {reason} |")
    w("")
    roles = [(r, next((s for s in skus if s.model_id == mid and s.label == lb), None))
             for r, mid, lb, _ in TIER_ROLES]
    priced = [(r, s) for r, s in roles if s is not None]
    missing = [r for r, s in roles if s is None]
    if missing:
        w(f"> ⚠️ 有档位定价缺失，未纳入跨度计算：{'、'.join(missing)}")
    if priced:
        lo = min(s.cost for _, s in priced)
        hi = max(s.cost for _, s in priced)
        w(f"五档的成本跨度 **{hi / lo:.1f} 倍**（{_money(lo)} → {_money(hi)}），"
          f"积分跨度 **{min(s.credits for _, s in priced)} → {max(s.credits for _, s in priced)}**。")
    w("")
    w("---")
    w("")

    # ── 7 方舟可用清单 ────────────────────────────────────────────────
    w("## 7. 豆包侧账号可用模型清单（`GET /api/v3/models` 实证）")
    w("")
    w("这一节回答的是「到底有哪些能调」，而不是「价目表上写了哪些」。")
    w("查询方式：")
    w("")
    w("```bash")
    w("curl -H \"Authorization: Bearer $ARK_API_KEY\" \\")
    w("  https://ark.cn-beijing.volces.com/api/v3/models")
    w("```")
    w("")
    w("该接口返回账号可见的**全部** 135 个模型，其中视频相关 12 个：")
    w("")
    w("| 模型 ID | 状态 | 任务类型 | 是否入积分表 |")
    w("| --- | --- | --- | --- |")
    for model_id, status, tasks in ARK_VIDEO_SNAPSHOT:
        if model_id in PRICING:
            included = "✅ 已入表"
        else:
            included = "❌ 未入表"
        w(f"| `{model_id}` | {status} | {tasks} | {included} |")
    w("")
    w("**未入表的 5 个，原因逐条写清楚：**")
    w("")
    for model_id, reason in ARK_UNPRICED_REASON.items():
        w(f"- `{model_id}`：{reason}")
    w("")
    w("> 另外 `wan2-1-14b-*` 三个是通义老模型托管在方舟上，状态已是**已下线**，")
    w("> 不要误以为是可用选项。")
    w("")
    w("---")
    w("")

    # ── 8 待核实 ──────────────────────────────────────────────────────
    w("## 8. 还没做完的部分（如实列出）")
    w("")
    w("| 项 | 状态 | 影响 | 怎么补 |")
    w("| --- | --- | --- | --- |")
    w("| 2.0 系（标准 / Fast / Mini）的 480P 与 1080P 费率 | ❌ 未取到 | 这三档目前只能报 720P 的价 | 方舟控制台价目页 |")
    w("| 实测与官方公式的偏差（720P +0.83%、480P +5.41%） | ⚠️ 未解释 | 报价可能略低于实际计费 | 各重测一次，核对 `usage.completion_tokens` |")
    w("| 2.5 的实测 tokens 量 | ❌ 未取证 | 2.5 的报价是按官方公式推的，未经实测交叉验证 | 跑一次真实 2.5 任务 |")
    w("| 2.5 视频编辑的时长计费 | ❌ 未验证 | 一次 5 秒编辑若带 10 秒输入，按 20 秒计费（¥18.14） | 实测一次视频编辑任务 |")
    w("| 各档质量对比样例 | ❌ 未做 | **用户无法判断多花 10 倍积分值不值** | 跑若干片段，约 ¥30 |")
    w("")
    w("**最要紧的是最后一条。** 价格表再准，用户看 31 个档位仍然不知道选哪个。")
    w("")
    w("---")
    w("")
    w("## 9. 相关文档")
    w("")
    w("| 文档 | 关系 |")
    w("| --- | --- |")
    w("| `积分与会员模型.md` | 积分账户、流水、订单、会员规则 |")
    w("| `组合计价.md` | 五档设计、特价机制、折扣安全下限 |")
    w("| `竞品定价调研.md` | 行业价格带对照 |")
    w("| `src/backend/models/pricing.py` | **价格的唯一来源**，每条带来源与核实状态 |")
    w("| `pricing_calc.py` | 换算公式的唯一来源 |")
    w("")
    w(f"> {EXCLUDED_NOTE}")
    w("")

    return "\n".join(out)


def check_ark() -> int:
    """重新查询方舟可用模型，与快照比对。不一致时打印差异并返回 1。"""
    cfg_path = os.path.join(_BACKEND, "config.yaml")
    if not os.path.exists(cfg_path):
        print(f"找不到 {cfg_path}", file=sys.stderr)
        return 2
    cfg = open(cfg_path, encoding="utf-8").read()
    m = re.search(r"ark:\s*\n\s*api_key:\s*(\S+)", cfg)
    base = re.search(r"ark:\s*\n(?:.*\n)*?\s*base_url:\s*(\S+)", cfg)
    if not m or not base:
        print("config.yaml 里找不到 ark.api_key / base_url", file=sys.stderr)
        return 2

    url = base.group(1).rstrip("/") + "/models"
    req = urllib.request.Request(url, headers={"Authorization": "Bearer " + m.group(1)})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.load(resp)["data"]
    except Exception as exc:  # 网络问题不该让校验假装通过
        print(f"查询失败：{exc}", file=sys.stderr)
        return 2

    kw = ("seedance", "sora", "kling", "veo", "pixverse", "vidu", "hailuo", "minimax")
    live = {d["id"] for d in data if any(k in d["id"].lower() for k in kw)}
    live |= {d["id"] for d in data if d["id"].startswith("wan2-1-14b")}
    snap = {row[0] for row in ARK_VIDEO_SNAPSHOT}

    added, removed = live - snap, snap - live
    print(f"方舟当前视频相关模型 {len(live)} 个，快照 {len(snap)} 个")
    if not added and not removed:
        print("✅ 与快照一致，文档第 7 节仍然有效")
        return 0
    for x in sorted(added):
        print(f"  ＋ 新增（快照里没有）：{x}")
    for x in sorted(removed):
        print(f"  － 消失（快照里有）：{x}")
    print("请更新 credits_table.py 的 ARK_VIDEO_SNAPSHOT 后重跑 --write", file=sys.stderr)
    return 1


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="生成千问/豆包视频模型积分换算表")
    ap.add_argument("--k", type=float, default=1.4, help="收费倍率，默认 1.4")
    ap.add_argument("--seconds", type=float, default=5.0, help="片段时长，默认 5 秒")
    ap.add_argument("--write", action="store_true", help=f"写入 {OUT_NAME}")
    ap.add_argument("--check", action="store_true", help="校验磁盘上的文档是否为最新")
    ap.add_argument("--check-ark", action="store_true", help="重新查询方舟可用模型并比对快照")
    args = ap.parse_args(argv[1:])

    if args.check_ark:
        return check_ark()

    text = render(args.k, args.seconds)
    target = os.path.join(_HERE, OUT_NAME)

    if args.check:
        if not os.path.exists(target):
            print(f"❌ {OUT_NAME} 不存在，请先跑 --write", file=sys.stderr)
            return 1
        on_disk = open(target, encoding="utf-8").read()
        if on_disk.rstrip("\n") != text.rstrip("\n"):
            print(f"❌ {OUT_NAME} 已过期：与当前定价/公式不一致，请重跑 --write", file=sys.stderr)
            return 1
        print(f"✅ {OUT_NAME} 是最新的")
        return 0

    if args.write:
        with open(target, "w", encoding="utf-8") as fh:
            fh.write(text)
        print(f"已写入 {target}")
        return 0

    print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
