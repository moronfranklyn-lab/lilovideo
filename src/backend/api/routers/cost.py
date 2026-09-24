"""成本查询接口。

对应 PRD 里"成本必须可见"这一条：
- 查询某会话已花费多少，以及花在哪个阶段、哪个模型上
- 生成前预估某个视频时长大概要花多少

设计约定
--------
- 成本无法计算时如实返回 `known: false`，**不返回 0 冒充免费**
- 含未核实定价时返回 `has_unverified: true`，让界面能提示"金额可能不准"
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from models import cost_store
from models.credits import DEFAULT_K, credits_for, margin, markup, yuan_per_credit
from models.cost import estimate_video_cost
from models.pricing import list_prices, unverified_models
from models.video_catalog import list_video_skus

router = APIRouter(tags=["Cost"])


@router.get("/api/cost/session/{session_id}")
async def get_session_cost(session_id: str):
    """查询一个会话的累计成本。

    无论有无记录都返回 200：新项目成本为 0 是正常状态，
    不应被当成错误处理。用 `call_count` 区分"没花过钱"与"还没开始"。
    """
    try:
        return cost_store.get_summary(session_id)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"读取成本失败: {exc}") from exc


class EstimateRequest(BaseModel):
    model_id: str = Field(..., description="视频模型 ID")
    seconds: float = Field(..., gt=0, description="预计视频总时长（秒）")
    resolution: str = Field("720P", description="分辨率，如 720P / 1080P")
    variant: str | None = Field(
        None,
        description='档位名，如 "720P 带音"。不传则用该模型的默认档。'
                    "传了但不存在时返回 known=false，**不会退回默认档报价**。",
    )


@router.post("/api/cost/estimate")
async def estimate_cost(req: EstimateRequest):
    """生成前预估视频成本。

    这是"生成前报价"的实现：用户在动手前就能知道大概要花多少。
    预估不到时返回 `known: false`，界面应显示"成本未知"而不是 0。

    注意 `verified` 字段的含义：通义系按秒定价，数字确定；
    Seedance 系按 tokens 计费，这里的金额是"官方费率 × 实测 tokens/秒"的
    换算估计，标 `verified: false`，不能当账单级精度用。
    """
    result = estimate_video_cost(
        req.model_id, req.seconds, resolution=req.resolution, variant=req.variant
    )
    if result is None:
        return {
            "known": False,
            "model_id": req.model_id,
            "seconds": req.seconds,
            "resolution": req.resolution,
            "variant": req.variant,
            "reason": "该模型未登记定价、档位不存在，或该分辨率没有实测依据，无法预估",
        }
    # 顺便给出积分，前端不必自己再算一遍（两边算会算出两个数）
    credits = credits_for(result.amount, DEFAULT_K)
    return {
        "known": True,
        "model_id": result.model_id,
        "seconds": req.seconds,
        "resolution": req.resolution,
        "variant": req.variant,
        "amount": result.amount,
        "currency": result.currency,
        "billing": result.billing,
        "verified": result.verified,
        "breakdown": result.breakdown,
        "credits": credits,
        "revenue": round(credits * yuan_per_credit(DEFAULT_K), 2),
    }


@router.get("/api/cost/video-models")
async def list_video_models(seconds: float = 5.0):
    """列出全部可售视频档位（模型 × 分辨率/音轨），含成本与积分。

    这是档位选择器的数据源。与文档《积分换算表.md》同源
    （都走 `models/video_catalog.py`），所以界面上显示的积分和
    文档里写的不会不一致。

    按每秒成本升序返回，最便宜的在前——这正是用户在界面上应该看到的顺序。
    """
    if seconds <= 0:
        raise HTTPException(status_code=422, detail="seconds 必须大于 0")
    skus = sorted(list_video_skus(k=DEFAULT_K, seconds=seconds), key=lambda s: s.cost)
    return {
        "seconds": seconds,
        "currency": "CNY",
        "k": DEFAULT_K,
        "yuan_per_credit": yuan_per_credit(DEFAULT_K),
        "markup": round(markup(DEFAULT_K), 4),
        "margin": round(margin(DEFAULT_K), 4),
        "count": len(skus),
        "items": [sku.to_dict() for sku in skus],
    }


@router.get("/api/cost/pricing")
async def get_pricing(provider: str | None = None):
    """列出定价注册表。

    同时返回未核实清单，便于界面统一提示哪些模型的成本数字不可靠。
    """
    items = list_prices(provider)
    return {
        "currency": "CNY",
        "count": len(items),
        "items": [
            {
                "model_id": p.model_id,
                "provider": p.provider,
                "billing": p.billing,
                "input_per_million": p.input_per_million,
                "output_per_million": p.output_per_million,
                "cached_input_per_million": p.cached_input_per_million,
                "per_second": p.per_second,
                "per_image": p.per_image,
                "verified": p.verified,
                "source": p.source,
                "note": p.note,
            }
            for p in items
        ],
        "unverified": unverified_models(),
    }
