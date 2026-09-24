"""积分接口。

第一版**不接真实支付**（已定决策 D17），所以没有下单与回调，
积分的入账由管理员手工触发。本文件提供：

- 查询余额与流水（用户看自己的钱）
- 对账检查（运维与演示用）
- 管理员发积分（**仅本机模式可用**）

安全设计
--------
发积分等于凭空造钱，所以 `POST /api/credits/grant` 在处理任何请求前先判断运行模式：
公网模式（监听非回环地址）下一律 403。判定方式与配置写接口一致，
由监听地址自动推导（见 `deployment.py`），不依赖使用者记得关开关。

这与成本接口的区别：成本接口是只读的，可以开放；积分写接口不行。
"""

from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from config import Config
from models import credits_store
from models.credits import DEFAULT_K, yuan_per_credit

router = APIRouter(tags=["Credits"])


def _require_local_mode(action: str) -> None:
    """写类操作只允许在本机模式下执行。"""
    if Config.IS_PUBLIC:
        raise HTTPException(
            status_code=403,
            detail=(
                f"公网模式下禁止{action}。"
                "该接口无鉴权，开放等于允许任何人凭空获取积分。"
            ),
        )


def _account_payload(user_id: str) -> dict:
    account = credits_store.get_account(user_id)
    ypc = yuan_per_credit(DEFAULT_K)
    return {
        **account,
        "currency": "CNY",
        "yuan_per_credit": ypc,
        # 直接给出"这些积分值多少钱"，前端不必自己算（两边算会算出两个数）
        "balance_value_yuan": round(account["balance"] * ypc, 2),
        "locked_value_yuan": round(account["locked"] * ypc, 2),
    }


@router.get("/api/credits/account")
async def get_account(user_id: str = credits_store.LOCAL_USER):
    """账户概览：可用余额、冻结中、累计获得与消耗。"""
    try:
        return _account_payload(user_id)
    except credits_store.CreditsError as exc:
        # 账本损坏时报 500 并说明原因，**不返回一个看起来正常的空账**
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/api/credits/ledger")
async def get_ledger(
    user_id: str = credits_store.LOCAL_USER,
    limit: int = 50,
    session_id: Optional[str] = None,
):
    """流水明细，最新在前。

    每笔都带 `balance_after`，所以界面可以逐笔展示"变动后余额"，
    对账时也能直接定位是哪一笔开始不对。
    """
    try:
        items = credits_store.get_ledger(user_id, limit=limit, session_id=session_id)
    except credits_store.CreditsError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return {"user_id": user_id, "count": len(items), "items": items}


@router.get("/api/credits/verify")
async def verify_ledger(user_id: str = credits_store.LOCAL_USER):
    """对账：检查 `sum(amount) == balance` 与 `balance_after` 链条是否自洽。

    返回空 `problems` 即账本健康。这是排查"账对不上"的第一站。
    """
    try:
        return credits_store.verify(user_id)
    except credits_store.CreditsError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


class GrantRequest(BaseModel):
    credits: int = Field(..., description="发放的积分数，必须为正")
    reason: str = Field("管理员发放", description="发放原因，会记进流水")
    user_id: str = Field(credits_store.LOCAL_USER, description="目标用户")
    ref: Optional[str] = Field(
        None,
        description="幂等键。传了就重复调用只发一次；不传则每次都发（慎用）。",
    )


@router.post("/api/credits/grant")
async def grant_credits(req: GrantRequest):
    """管理员发放积分。

    **仅本机模式可用**——这个接口没有鉴权，公网开放等于允许任何人给自己发钱。

    第一版没有真实支付，用户买积分的路径是"线下付款 → 管理员在这里发放"。
    真实支付接入后（阶段 4），入账应改为由支付回调触发，本接口保留为运营兜底。
    """
    _require_local_mode("发放积分")
    try:
        txn = credits_store.grant(
            req.user_id, req.credits, req.reason, ref=req.ref
        )
    except credits_store.CreditsError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"transaction": txn, "account": _account_payload(req.user_id)}


@router.post("/api/credits/signup-bonus")
async def signup_bonus(user_id: str = credits_store.LOCAL_USER):
    """发放注册赠送（300 积分，一次性）。

    靠固定 ref 幂等，所以重复调用不会重复发放。
    目前没有账号体系，这个接口供本机首次初始化使用；接入登录后应由注册流程调用。
    """
    _require_local_mode("发放注册赠送")
    try:
        txn = credits_store.grant_signup_bonus(user_id)
    except credits_store.CreditsError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"transaction": txn, "account": _account_payload(user_id)}
