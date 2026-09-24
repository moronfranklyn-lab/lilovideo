#!/usr/bin/env python3
"""积分定价计算器。

为什么要有这个脚本
------------------
定价文档里每个数字都互相牵制：改倍率会影响所有消耗值、影响每条成片的毛利、
影响会员赠积分的价值。手写这些数字必然出现不一致——本项目已经踩过一次：
同一份文档里写着「免费 300 积分」和「一次闭环需 2,220 积分」，自相矛盾。

所以定价表不手写，由本脚本生成。改参数后重跑，全部数字同步更新。

公式的唯一来源
--------------
换算公式**不在本文件里**，在 `src/backend/models/credits.py`。
这里只是把它 import 进来用。

这样做的原因：公式决定了每一次扣费。如果代码里一份、文档里一份，
迟早出现"文档说 71.4%、代码算出 79.6%"这种局面——而本项目**真的发生过**
（见《积分与会员模型.md》§2.4，K 在积分和单价里各出现一次，
实付倍数是 2.5K² 而不是 2.5K）。

规则
----
    积分消耗 = 成本(元) × 10 × K        K 为收费倍率
    1 积分售价 = K × 0.25 元
    实付倍数 = 10 × K × (K × 0.25) = 2.5K²
    毛利 = 1 − 1/(2.5K²)

用法
    python3 pricing_calc.py            # 打印全部推导与表格
    python3 pricing_calc.py --k 2.0    # 换倍率看结果
"""

from __future__ import annotations

import argparse
import os
import sys

# 换算公式的唯一来源在后端；把后端目录挂进 sys.path 才能 import。
# 放在 import 之前是必须的——这是本文件唯一一处"脏"的地方，
# 换来的是公式只有一份。
_BACKEND = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "src", "backend",
)
if _BACKEND not in sys.path:
    sys.path.insert(0, _BACKEND)

from models.credits import (  # noqa: E402
    CREDITS_PER_YUAN_COST,
    DEFAULT_K,
    YUAN_PER_CREDIT_UNIT,
    credits_for,
    discount_floor,
    margin,
    markup,
    yuan_per_credit,
)

# 默认档（Seedance 2.0）的视频成本，按官方公式推算。
# 算不出来时回退到 0 并在积分表里显形（而不是静默用一个旧数字）。
def _vod(seconds: float):
    from models.cost import estimate_video_cost
    r = estimate_video_cost("doubao-seedance-2-0-260128", seconds)
    return round(r.amount, 2) if r else 0.0


# 实测成本（元）。来源：真实预跑 + 官方定价换算。
MEASURED = {
    # ⚠️ 0.72 是**用 qwen-max 跑出来的**（2026-09-22 真实预跑）。
    # 2026-09-23 主用 LLM 已换成 DeepSeek V4.1 Flash，这个数**需要重新实测**。
    # 抽样对比（一次短问答）：qwen-max ¥0.00294 vs DeepSeek ¥0.00122，便宜约 58%；
    # 但它是推理模型、输出 tokens 含 reasoning，长短文比值未必一致，
    # 不能靠抽样外推，要跑一次真实剧本生成才能定。
    "script_generation": ("剧本生成", 0.72),
    "storyboard":        ("分镜规划", 0.94),
    "vlm_eval":          ("图片评估", 0.26),
    "image":             ("单张图（角色/场景/参考图）", 0.20),
    # 视频成本改为**从定价注册表按官方公式推算**，不再手写。
    #
    # 为什么改：早先这里写死 5.01 / 9.98，是「实测 108,900 tokens × 46 元/百万」
    # 与「按倍数外推」两个来源混出来的。现在官方价目页给出了统一公式
    #   Token用量 = 宽 × 高 × 帧率 × 时长 ÷ 1024
    # 并且 6 行示例全部吻合，所以报价统一以官方公式为准。
    #
    # 实测偏差如实记录：真实预跑那次 5 秒 720P 实际计费 108,900 tokens
    # （官方公式给 108,000，实测高 0.83%，约 ¥0.04）——不影响积分（都是 70）。
    # 成本记账走 API 返回的真实用量，不受这里影响。
    "video_5s":          ("视频片段 5 秒", _vod(5)),
    "video_10s":         ("视频片段 10 秒", _vod(10)),
}


def report(k: float) -> None:
    ypc = yuan_per_credit(k)
    m = margin(k)
    print(f"收费倍率 K = {k}")
    print(f"  1 积分售价     = ¥{ypc:.4f}   （= K × {YUAN_PER_CREDIT_UNIT}）")
    print(f"  用户实付 / 成本 = {markup(k):.2f} 倍   （= {CREDITS_PER_YUAN_COST} × {k} × {ypc:.2f} = 2.5K²）")
    print(f"  毛利           = {m:.1%}")
    print(f"  折扣安全下限   = {discount_floor(k):.1%}   （毛利为 0 的折扣率）")
    print()

    print("单项积分消耗")
    print(f"  {'操作':<28}{'成本':>8}{'积分':>8}")
    print("  " + "-" * 44)
    table = {}
    for key, (name, cost) in MEASURED.items():
        c = credits_for(cost, k)
        table[key] = c
        print(f"  {name:<28}¥{cost:>7.2f}{c:>8}")

    # 一条 10 秒成片：前期全流程 + 2 个片段 + 1 次视频重做
    parts = [
        ("剧本生成", table["script_generation"], MEASURED["script_generation"][1]),
        ("分镜规划", table["storyboard"],        MEASURED["storyboard"][1]),
        ("角色图 × 3", table["image"] * 3,       MEASURED["image"][1] * 3),
        ("场景图 × 1", table["image"],           MEASURED["image"][1]),
        ("参考图 × 4", table["image"] * 4,       MEASURED["image"][1] * 4),
        ("视频片段 × 2 + 重做 1 次", table["video_5s"] * 3, MEASURED["video_5s"][1] * 3),
    ]
    tc = sum(p[1] for p in parts)
    tcost = sum(p[2] for p in parts)
    revenue = tc * ypc

    print()
    print("一条 10 秒成片（含 1 次视频重做）")
    print(f"  {'步骤':<28}{'积分':>8}{'成本':>10}")
    print("  " + "-" * 46)
    for name, c, cost in parts:
        print(f"  {name:<28}{c:>8}¥{cost:>9.2f}")
    print("  " + "-" * 46)
    print(f"  {'合计':<28}{tc:>8}¥{tcost:>9.2f}")
    print()
    actual_margin = (revenue - tcost) / revenue
    designed = margin(k)
    print(f"  用户实付 = {tc} × ¥{ypc:.4f} = ¥{revenue:.2f}")
    print(f"  真实成本 = ¥{tcost:.2f}")
    print(f"  实例毛利 = {actual_margin:.1%}")
    print()
    print(f"  设计毛利 {designed:.1%} vs 实例毛利 {actual_margin:.1%}，差 {actual_margin - designed:+.1%}")
    print("  差异来源：低价值项取整到整数积分时会向上取整。")
    print("  例：单张图成本 ¥0.20，按公式为 2.8 积分，取整为 3 积分，等效多收约 7%。")
    print("  高价项（视频）取整误差可忽略，因此成片整体毛利略高于设计值。")
    print()
    print("  ⚠️ 历史提醒：这里的『设计毛利』曾经是 71.4%，而实例毛利是 79.7%，")
    print("     两者差 8.2% 被解释成取整误差——但取整不可能造成 8 个点的偏差。")
    print("     真实原因是实付倍数被按 2.5K 记账，而正确值是 2.5K²（K 在积分和")
    print("     单价里各出现一次）。修正后设计毛利 = 79.6%，与实例毛利只差取整。")
    print("     详见《积分与会员模型.md》§2.4。")

    # 最小闭环（到看到动态画面）
    minimal = table["script_generation"] + table["storyboard"] + table["image"] * 2 + table["image"] * 2 + table["video_5s"]
    print()
    print("最小闭环（创意 → 看到 5 秒动态画面）")
    print(f"  消耗 = {minimal} 积分")
    grant = 300
    print(f"  注册赠送 {grant} 积分 → {'够用' if grant >= minimal else '不够'}，余量 {grant - minimal}")

    print()
    print("积分卡建议（按 10 秒成片条数定价，取整到易读价）")
    for name, n_pics in [("体验", 0.3), ("标准", 1), ("创作者", 3), ("工作室", 10)]:
        c = int(round(tc * n_pics / 10) * 10)
        price = c * ypc
        rounded_price = round(price / 10) * 10 if price >= 100 else round(price)
        print(f"  {name:<8}{c:>6} 积分  原价 ¥{price:>7.0f}  建议定价 ¥{rounded_price}")


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--k", type=float, default=1.4, help="收费倍率，默认 1.4（定稿值）")
    args = ap.parse_args(argv[1:])
    report(args.k)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
