"""可售视频档位目录。

把"用户能买哪些视频档位、各要多少积分"这件事集中到一个地方。

为什么要有这个模块
------------------
定价注册表（`pricing.py`）回答的是"这个模型多少钱"，而产品要回答的是
"用户在界面上看到的这个选项多少钱"。两者之间隔着一层展开：

- 一个模型可能有 1–4 个档位（480P / 720P 无声 / 720P 带音 / 1080P 带音），
  每个档位是**独立的一个可售项**
- 两种计费口径：通义按秒（直接乘）、豆包按 tokens（要先按实测口径折成 tokens）
- 还要叠加积分换算

这层展开逻辑原先写在文档生成脚本里，结果就是"接口能报的价"和
"文档里写的价"是两套代码算的。放在这里之后三者共用一份：

    定价注册表 → 本模块 → ┬→ API（生成前报价、档位选择器）
                          └→ 文档（积分换算表.md，脚本生成）

产品展示名
----------
本模块带中文展示名，因为同一个模型在界面、文档、客服话术里必须是同一个名字。
早先文档里 wan2.6-flash 一处叫"入门"、另一处叫"特价"，
前端照哪份做都会错——名字只能有一个来源。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from models.credits import DEFAULT_K, credits_for, yuan_per_credit
from models.pricing import PRICING, seedance_tokens

# ── 展示名 ─────────────────────────────────────────────────────────────
DISPLAY_NAMES: dict[str, str] = {
    "wan2.6-i2v-flash": "万相 2.6 图生视频 Flash",
    "wan2.6-i2v": "万相 2.6 图生视频",
    "wan2.7-i2v": "万相 2.7 图生视频",
    "wan2.6-r2v": "万相 2.6 参考生视频",
    "wan2.6-r2v-flash": "万相 2.6 参考生视频 Flash",
    "wan2.7-r2v": "万相 2.7 参考生视频",
    "wan2.6-t2v": "万相 2.6 文生视频",
    "wan2.7-t2v": "万相 2.7 文生视频",
    "happyhorse-1.0-i2v": "HappyHorse 1.0 图生视频",
    "happyhorse-1.1-i2v": "HappyHorse 1.1 图生视频",
    "doubao-seedance-2-5-260628": "Seedance 2.5",
    "doubao-seedance-2-0-260128": "Seedance 2.0",
    "doubao-seedance-2-0-fast-260128": "Seedance 2.0 Fast",
    "doubao-seedance-2-0-mini-260615": "Seedance 2.0 Mini",
}

VENDOR_DASHSCOPE = "千问·通义"
VENDOR_ARK = "豆包·Seedance"


@dataclass(frozen=True)
class VideoSku:
    """一个可售档位：模型 × 分辨率/音轨。"""

    model_id: str
    display: str          # 中文展示名
    vendor: str
    kind: str             # 图生视频 / 参考生视频 / 文生视频
    label: str            # 档位名，如 "720P 带音"
    seconds: float
    cost: float           # 本次生成的真实成本（元）
    credits: int          # 用户需付的积分
    verified: bool
    per_second: Optional[float] = None    # 每秒成本（元）
    per_million_tokens: Optional[float] = None
    tokens: Optional[int] = None          # 按 tokens 计费时的用量（取整后的展示值）
    # 官方公式会算出小数（如 480P 5 秒 = 48,037.5），保留原值供核对
    token_count: Optional[float] = None

    @property
    def key(self) -> str:
        """稳定标识，供前端做选项 key。"""
        return f"{self.model_id}@{self.label}"

    @property
    def revenue(self) -> float:
        """用户实付金额。"""
        return self.credits * yuan_per_credit(DEFAULT_K)

    def to_dict(self) -> dict:
        return {
            "key": self.key,
            "model_id": self.model_id,
            "display": self.display,
            "vendor": self.vendor,
            "kind": self.kind,
            "label": self.label,
            "seconds": self.seconds,
            "cost": round(self.cost, 4),
            "per_second": round(self.per_second, 4) if self.per_second is not None else None,
            "per_million_tokens": self.per_million_tokens,
            "tokens": self.tokens,
            "token_count": self.token_count,
            "credits": self.credits,
            "revenue": round(self.revenue, 2),
            "verified": self.verified,
        }


def _display_name(model_id: str) -> str:
    return DISPLAY_NAMES.get(model_id, model_id)


def _kind_of(model_id: str) -> str:
    if "-r2v" in model_id:
        return "参考生视频"
    if "-t2v" in model_id:
        return "文生视频"
    return "图生视频"


def object_kind(model_id: str) -> str:
    """公开给外部的 kind 查询（文档脚本也会用）。"""
    return _kind_of(model_id)


def list_video_skus(k: float = DEFAULT_K, seconds: float = 5.0) -> list[VideoSku]:
    """列出全部可售视频档位。

    只纳入**视频生成**模型：``per_second`` 的（通义）与带实测 tokens/秒 的
    per_token 模型（Seedance）。LLM / VLM / 图片模型不在范围内。

    百炼上另有 s2v（语音驱动）、animate（换脸）、videoedit（视频编辑）、
    liveportrait 等专用模型，以及 kling / vidu / pixverse / MiniMax 等
    第三方托管模型——它们不是"生视频"，本产品不接，故不列出。
    """
    skus: list[VideoSku] = []
    for model_id, spec in sorted(PRICING.items()):
        is_dashscope = spec.provider == "dashscope"
        is_seedance = spec.provider == "ark" and spec.tokens_per_second_720p

        if is_dashscope and spec.billing != "per_second":
            continue
        if spec.provider == "ark" and not is_seedance:
            continue
        if not is_dashscope and not is_seedance:
            continue

        vendor = VENDOR_DASHSCOPE if is_dashscope else VENDOR_ARK
        kind = _kind_of(model_id)

        if spec.billing == "per_second":
            for label, unit in spec.variants:
                cost = unit * seconds
                skus.append(VideoSku(
                    model_id=model_id, display=_display_name(model_id), vendor=vendor,
                    kind=kind, label=label, seconds=seconds, cost=cost,
                    credits=credits_for(cost, k), verified=spec.verified,
                    per_second=unit,
                ))
        else:
            # Seedance：费率按分辨率分档（2.5 的 1080P 是 77，480P/720P 是 70），
            # 所以逐档展开。**只展开登记过费率的档位**——
            # 2.0 系只取到 720P 的费率，就不给它编 480P/1080P 的价。
            for label, rate in spec.token_rate_variants:
                tokens = seedance_tokens(seconds, label)
                if not tokens:
                    continue
                cost = tokens / 1_000_000 * rate
                skus.append(VideoSku(
                    model_id=model_id, display=_display_name(model_id), vendor=vendor,
                    kind=kind, label=label, seconds=seconds, cost=cost,
                    credits=credits_for(cost, k), verified=spec.verified,
                    per_second=cost / seconds, per_million_tokens=rate,
                    tokens=int(round(tokens)),
                    token_count=tokens,
                ))
    return skus


def find_sku(model_id: str, label: str, k: float = DEFAULT_K,
             seconds: float = 5.0) -> Optional[VideoSku]:
    """按模型 ID + 档位名查找。找不到返回 None（不猜一个近似档位）。"""
    for sku in list_video_skus(k, seconds):
        if sku.model_id == model_id and sku.label == label:
            return sku
    return None
