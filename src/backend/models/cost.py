"""成本计算。

依据 `models/pricing.py` 的定价注册表，把一次模型调用的用量换算成人民币金额。

设计原则
--------
1. **算不出来就说算不出来**：找不到定价、或用量字段缺失时返回 `None`，
   绝不猜测。调用方据此显示"成本未知"，而不是显示一个编造的数字。
2. 纯函数，不读写磁盘、不发网络请求，便于单测。
3. 每个结果都带 `verified` 标记，让上层能区分"真实价格算出的"与"占位价格算出的"。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from models.pricing import PriceSpec, get_price, seedance_tokens


@dataclass
class Usage:
    """一次模型调用的用量。字段按计费方式使用，不适用的留空。

    这里只装「客户端观察到的**输入事实**」，不装价格判断。
    「720P 带音对应哪一档、每秒多少钱」由定价层（`pricing.PriceSpec.resolve`）
    决定——否则档位解释权会散到每个客户端里，改价目表就得改客户端。
    """

    model_id: str
    # per_token 用
    input_tokens: int = 0
    output_tokens: int = 0
    cached_input_tokens: int = 0
    # per_second 用
    seconds: float = 0.0
    resolution: Optional[str] = None   # 如 "720P" / "1080P"，用于定位档位
    audio: Optional[bool] = None       # 是否带音轨，用于定位档位
    # per_image 用
    images: int = 0


@dataclass
class CostResult:
    """成本计算结果。"""

    model_id: str
    amount: float
    currency: str
    billing: str
    verified: bool
    # 便于界面解释"这笔钱是怎么来的"
    breakdown: str


def compute_cost(usage: Usage) -> Optional[CostResult]:
    """计算单次调用成本。

    返回 `None` 表示**无法计算**（未登记定价，或所需用量字段为 0）。
    调用方必须处理 None，不得用 0 代替——"免费"与"未知"是两件事。
    """
    spec: Optional[PriceSpec] = get_price(usage.model_id)
    if spec is None:
        return None

    if spec.billing == "per_token":
        if not usage.input_tokens and not usage.output_tokens:
            return None
        return _cost_per_token(usage, spec)

    if spec.billing == "per_second":
        if not usage.seconds or spec.per_second is None:
            return None

        # 先按客户端报的分辨率/音轨定位档位；定位不到就退回默认档，
        # 但**明确指定却找不到**时必须报"未知"——否则 1080P 会被按 720P 记账。
        unit = spec.per_second
        label = spec.unit_label or "默认档"
        if usage.resolution is not None or usage.audio is not None:
            resolved = spec.resolve(usage.resolution, usage.audio)
            if resolved is None and spec.variants:
                return None
            if resolved is not None:
                label, unit = resolved

        amount = usage.seconds * unit
        return CostResult(
            model_id=spec.model_id,
            amount=round(amount, 6),
            currency="CNY",
            billing=spec.billing,
            verified=spec.verified,
            breakdown=f"{usage.seconds:g} 秒 × {unit} 元/秒（{label}）",
        )

    if spec.billing == "per_image":
        if not usage.images or spec.per_image is None:
            return None
        amount = usage.images * spec.per_image
        return CostResult(
            model_id=spec.model_id,
            amount=round(amount, 6),
            currency="CNY",
            billing=spec.billing,
            verified=spec.verified,
            breakdown=f"{usage.images} 张 × {spec.per_image} 元/张",
        )

    # 未知计费方式：按无法计算处理，不猜测
    return None


def _cost_per_token(usage: Usage, spec: PriceSpec) -> Optional[CostResult]:
    """按 tokens 计费。

    缓存命中的输入单独计价（通常更便宜），因此从 input_tokens 中扣除，
    避免同一批 tokens 被计价两次。
    """
    if spec.input_per_million is None and spec.output_per_million is None:
        return None

    cached = min(usage.cached_input_tokens, usage.input_tokens)
    fresh_input = max(usage.input_tokens - cached, 0)

    in_rate = spec.input_per_million or 0.0
    out_rate = spec.output_per_million or 0.0
    cache_rate = spec.cached_input_per_million

    # 没登记缓存价时，缓存命中的 tokens **按普通输入价计费**，而不是免费。
    #
    # 这里原先是个静默少算的 bug：`if cached and cache_rate is not None` 意味着
    # 只要没登记缓存价，这部分 tokens 就一分钱不算。
    # 30 万缓存 tokens 会凭空消失成 ¥0，而且不报错、不留痕。
    # 缓存命中的正确定价只会**更便宜**，不可能免费，所以退到普通输入价是安全方向。
    effective_cache_rate = cache_rate if cache_rate is not None else in_rate

    amount = fresh_input / 1_000_000 * in_rate
    amount += usage.output_tokens / 1_000_000 * out_rate
    if cached:
        amount += cached / 1_000_000 * effective_cache_rate

    parts = []
    if fresh_input:
        parts.append(f"输入 {fresh_input} tokens × {in_rate} 元/百万")
    if cached:
        suffix = "" if cache_rate is not None else "（未登记缓存价，按输入价计）"
        parts.append(f"缓存命中 {cached} tokens × {effective_cache_rate} 元/百万{suffix}")
    if usage.output_tokens:
        parts.append(f"输出 {usage.output_tokens} tokens × {out_rate} 元/百万")

    return CostResult(
        model_id=spec.model_id,
        amount=round(amount, 6),
        currency="CNY",
        billing=spec.billing,
        verified=spec.verified,
        breakdown="；".join(parts) if parts else "无用量",
    )


def token_rate(
    spec: PriceSpec,
    resolution: Optional[str] = None,
    with_video_input: bool = False,
) -> Optional[float]:
    """取出该分辨率的 token 费率（元/百万 tokens）。取不到返回 None。

    费率**分分辨率**：Seedance 2.5 的 1080P 是 77，而 480P/720P 是 70。
    所以不能只看 `output_per_million`——那会把 1080P 按 70 报价，少收 9%。

    取不到的两种情况都当"不能报价"处理：
    - 该模型没登记分档费率（LLM；以及 2.0 系只登记了 720P）
    - 登记了费率表，但**没有这个分辨率**
    """
    if spec.token_rate_variants or spec.token_rate_variants_with_input:
        return spec.resolve_token_rate(resolution, with_video_input)
    return spec.output_per_million or spec.input_per_million


def estimate_video_cost(
    model_id: str,
    seconds: float,
    resolution: str = "720P",
    variant: Optional[str] = None,
) -> Optional[CostResult]:
    """生成前的视频成本预估。

    两种计费方式，两条路径：

    - ``per_second``（通义系）：直接可用。传 ``variant`` 指定档位
      （如 ``"720P 带音"``），不传则用默认档 ``spec.per_second``。
      成本**完全确定**，因此标记 verified 跟随定价本身的核实状态。
    - ``per_token``（Seedance 系）：价目表给的是"元/百万 tokens"，
      要先把秒数折成 tokens 才能报价。折算系数是**实测**得到的
      （见 `pricing.SEEDANCE_TOKENS_PER_SECOND_720P`），
      因此结果标记 verified=False —— 它是可靠估算，但不是账单级精度。

    返回 None 表示该模型无法预估，界面应显示"成本未知"，**不得显示 0**。
    """
    spec = get_price(model_id)
    if spec is None:
        return None

    if spec.per_second is not None:
        unit = spec.per_second
        label = spec.unit_label or "默认档"

        if variant is not None:
            # 指定了档位就必须命中，否则报"未知"——不能悄悄退回默认档报价，
            # 那样用户以为买的是 1080P，账却按 720P 算。
            found = dict(spec.variants).get(variant)
            if found is None:
                return None
            unit, label = found, variant
        elif spec.variants:
            allowed = {name.split()[0] for name, _ in spec.variants}
            if resolution not in allowed:
                return None

        amount = seconds * unit
        return CostResult(
            model_id=spec.model_id,
            amount=round(amount, 6),
            currency="CNY",
            billing=spec.billing,
            verified=spec.verified,
            breakdown=f"{seconds:g} 秒 × {unit} 元/秒（{label}）",
        )

    if spec.billing == "per_token" and spec.tokens_per_second_720p:
        # 费率按分辨率取；该分辨率没登记费率时返回 None，
        # 而不是拿 720P 的费率去充 1080P（那会少收 9%）。
        rate = token_rate(spec, resolution)
        if rate is None:
            return None
        # 用量按官方公式算；分辨率没登记时同样返回 None。
        tokens = seedance_tokens(seconds, resolution)
        if not tokens:
            return None
        amount = tokens / 1_000_000 * rate
        per_second = amount / seconds if seconds else 0.0
        return CostResult(
            model_id=spec.model_id,
            amount=round(amount, 6),
            currency="CNY",
            billing="per_second_approx",
            verified=False,  # 换算估计，不是直接定价
            breakdown=(
                f"{seconds:g} 秒 {resolution} ≈ {tokens:,.1f} tokens × {rate:g} 元/百万"
                f"（约 {per_second:.2f} 元/秒；换算估计，非账单级精度）"
            ),
        )

    return None
