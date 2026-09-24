"""积分换算。

一层很薄的换算：把「真实成本（元）」换成「面向用户的积分」。

为什么积分与成本要分成两层
--------------------------
引自《积分与会员模型.md》§9：

    底层：成本核算  记录每次模型调用的真实花费 → 对账、核算毛利、发现异常
            ↓ 按倍率换算
    上层：积分计费  面向用户的可消费单位   → 扣费、定价、会员权益

**为什么不用积分直接记账**：成本层需要真实金额才能判断某条任务是否亏本；
积分层需要稳定换算，不能因为模型调价就让用户手里的积分贬值。
模型调价时只改倍率 K，用户余额不受影响。

为什么换算系数放在代码里而不是文档里
------------------------------------
这几个常数（10、0.25、K）决定了**每一次扣费**。如果只写在 markdown 里，
任何人都可能在文档里改一个数、而代码里还是旧值——用户就被扣错了钱。
所以代码是唯一来源，文档由脚本从代码生成。

本项目已经踩过一次同类坑：折扣安全下限在文档里是 20.4%、在校验脚本里算成 28.6%，
两个数都能自圆其说，只有逐项复算才发现脚本把系数写成了 2.5K。
现在 `discount_floor()` 就是那个系数，不再靠人记。

计费基准
--------
    积分消耗 = 成本(元) × CREDITS_PER_YUAN_COST × K
    1 积分售价 = K × YUAN_PER_CREDIT_UNIT 元
    毛利      = 1 − 1 / (CREDITS_PER_YUAN_COST × YUAN_PER_CREDIT_UNIT × K)
"""

from __future__ import annotations

from decimal import ROUND_HALF_EVEN, Decimal

# 积分基准：10 积分 = 1 元成本。
#
# 为什么是 10 而不是 100：视频片段成本约 ¥1–8，换算后是 10–112 积分，
# 用户能一眼读懂；文本类只要个位数积分，量级差异明显。
# 若用 100:1，视频会变成四位数，用户无法心算。
CREDITS_PER_YUAN_COST = 10

# 积分基础单价系数：1 积分 = K × 0.25 元。
# 这个 0.25 不是独立决策，它是"10 积分/元 × 0.25 = 2.5 倍成本"的锚点，
# 与 CREDITS_PER_YUAN_COST 一起决定实付倍数。
YUAN_PER_CREDIT_UNIT = 0.25

# 定稿倍率。选 1.4 的理由见《积分与会员模型.md》§2：
# 毛利要覆盖支付通道费（2–6%）、云资源、失败重试与人工成本。
# 对应毛利 79.6%（= 1 − 1/(2.5 × 1.4²)），实付倍数 4.90 倍。
#
# 这个 79.6% 落在《竞品定价调研.md》实测的行业区间 79–82% 内，
# 所以 K = 1.4 不需要再调。
DEFAULT_K = 1.4


def credits_for(cost_yuan: float, k: float = DEFAULT_K, round_to: int = 1) -> int:
    """成本换算为积分，取整到易读数值。

    为什么用 Decimal 而不是 float
    ----------------------------
    浮点误差会让"刚好落在 .5"的值随机偏一边，而这不是策略，是 bug。实测到两例：

        成本 ¥0.75 → 公式给 10.5 → float 算成 10.499999999999998 → 取整 10
        成本 ¥2.25 → 公式给 31.5 → float 算成 31.499999999999996 → 取整 31

    同样是 .5 却落在同一侧，纯属巧合：成本 ¥1.25 会算成 17.500000000000004
    → 取整 18，偏上。三个 .5 分两派，无法解释。

    现在统一为 **四舍六入五成双**（ROUND_HALF_EVEN）：.5 进到最近的偶数。
    这个规则下已公布的五档数值（10 / 21 / 42 / 56 / 70）**全部保持不变**。
    """
    raw = Decimal(str(cost_yuan)) * CREDITS_PER_YUAN_COST * Decimal(str(k))
    if round_to <= 1:
        return int(raw.quantize(Decimal(1), rounding=ROUND_HALF_EVEN))
    steps = (raw / Decimal(round_to)).quantize(Decimal(1), rounding=ROUND_HALF_EVEN)
    return int(steps * round_to)


def yuan_per_credit(k: float = DEFAULT_K) -> float:
    """1 积分卖多少钱。"""
    return k * YUAN_PER_CREDIT_UNIT


def revenue_for(credits: int, k: float = DEFAULT_K) -> float:
    """n 积分对应多少实付金额。"""
    return credits * yuan_per_credit(k)


def markup(k: float = DEFAULT_K) -> float:
    """实付倍数：用户付的钱是成本的几倍。

    **这里必须带 K 的平方，这是本项目一个真实算错过的地方。**

    两条公式里 K 各出现一次：

        积分 = 成本 × 10 × K          ← K 第一次
        实付 = 积分 × (K × 0.25)      ← K 第二次（单价本身也是 K 的函数）

    代入得：

        实付 = 成本 × 10 × K × K × 0.25 = 成本 × 2.5K²

    所以实付倍数是 **2.5K²**，不是 2.5K。K = 1.4 时是 **4.90 倍**，不是 3.5 倍。

    （历史：文档与脚本原先都按 2.5K 记账，得到"设计毛利 71.4%"。
    但文档里另外三处**由例子直接算出**的数字——打 5 折后毛利 59%、
    折扣安全下限 20.4%、实例毛利 79.7%——全部只与 4.90 倍自洽。
    也就是说 71.4% 才是那个孤立的错值，20.4% 一直是对的，
    只是被用错误的代数式"证明"过。详见《积分与会员模型.md》§2.4。）
    """
    return CREDITS_PER_YUAN_COST * YUAN_PER_CREDIT_UNIT * k * k


def margin(k: float = DEFAULT_K) -> float:
    """设计毛利 = 1 − 1/实付倍数 = 1 − 1/(2.5K²)。"""
    return 1 - 1 / markup(k)


def discount_floor(k: float = DEFAULT_K) -> float:
    """折扣的安全下限（毛利刚好为 0 的那个折扣率）。

    某档打 X 折时：``实付 = 成本 × 2.5K² × X``，不亏本要求 ``2.5K² × X > 1``：

        X > 1 / (2.5K²)

    K = 1.4 时为 **20.4%**——即打 2 折以上都不亏本（毛利为 0）。
    这只是不亏本；要保住基本毛利需另设目标，见《组合计价.md》§3.3。
    """
    return 1 / markup(k)

