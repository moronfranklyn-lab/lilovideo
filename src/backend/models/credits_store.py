"""积分账户与流水。

面向用户可消费单位（积分）的账本。规则定稿在《积分与会员模型.md》，这里实现它。

与成本层的关系
--------------
    成本层（cost_store）：记录每次模型调用的**真实花费（元）** → 对账、核算毛利
            ↓ 按倍率换算（models/credits.py）
    积分层（本模块）    ：记录用户**可用余额与每一笔变动** → 扣费、定价、会员权益

两层由**会话 ID** 关联，但不是同一份数据：
成本层需要真实金额才能判断某条任务是否亏本；积分层需要稳定换算，
不能因为模型调价就让用户手里的积分贬值。所以模型调价只改倍率 K，
用户余额不受影响。

三条设计决策（都是踩过或差点踩的坑）
------------------------------------
1. **余额只存一个地方**，不设"冻结中"字段。扣减走「预扣 → 确认 / 退回」，
   冻结状态体现在**流水的 status 上**，而不是在账户里再开一个计数器。
   两个地方记同一件事，迟早对不上。

2. **每笔流水都记 `balance_after`**。只记变动额的话，一旦对账出现差异
   就无法定位是哪一笔开始错的。

3. **`amount` 一律只做加法，退回靠新增一笔反向流水，不去改原记录**。
   于是有一条很好用的强不变式：

       sum(所有流水的 amount) == 账户余额

   任何时刻都能用它一眼验出账本是否被写坏。若退回时去改原记录，
   这条不变式就不成立了，对账也就失去了最简单的抓手。

资金安全的边界（如实说明）
--------------------------
- 余额**永不允许为负**：余额不足时抛 `InsufficientCredits`，不静默透支
- 预扣/确认/退回都按 `ref` 幂等：同一个 `ref` 重复调用不会重复扣费。
  这一条很关键——orchestrator 可能重试、用户可能连点，
  没有幂等就会出现"点一次扣两次"
- 确认时**实际用量可能超过预扣**。超出的部分若余额够就补扣；
  不够则扣到 0 并把缺口记在流水的 `shortfall` 上（同时 WARN），
  **不隐藏缺口，也不让余额变负**
"""

from __future__ import annotations

import json
import logging
import os
import threading
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

from config import BASE_DIR
from models.credits import DEFAULT_K, credits_for

logger = logging.getLogger(__name__)

# 账本目录。可用环境变量覆盖，便于工具与测试写到临时目录。
CREDITS_DIR = os.environ.get("LILOVIDEO_CREDITS_DIR") or os.path.join(
    BASE_DIR, "code", "data", "credits"
)

# 唯一的本地用户。
#
# 第一版不需要登录（已定决策），所以账本按固定用户 ID 记账。
# 结构上仍然是"按用户分文件"，等 D15 的账号体系落地后换成真实 user_id 即可，
# 不必改数据结构——这是刻意的，避免以后要从头重构账本格式。
LOCAL_USER = "local"

# 流水类型
TYPE_GRANT = "grant"        # 赠送（注册赠送、活动、会员每月赠）
TYPE_PURCHASE = "purchase"  # 购买积分卡
TYPE_CONSUME = "consume"    # 消费
TYPE_REFUND = "refund"      # 退回

# 流水状态。预扣产生的消费流水先是 pending，阶段结束再定终态。
STATUS_PENDING = "pending"
STATUS_CONFIRMED = "confirmed"
STATUS_RELEASED = "released"

# 注册赠送额度（PRD 与《积分与会员模型.md》§7 定稿）
SIGNUP_GRANT = 300

_locks: dict[str, threading.Lock] = {}
_locks_guard = threading.Lock()


class InsufficientCredits(Exception):
    """余额不足。带上缺口金额，便于界面直接展示。"""

    def __init__(self, required: int, balance: int, user_id: str):
        self.required = required
        self.balance = balance
        self.shortfall = required - balance
        super().__init__(
            f"积分不足：需要 {required}，当前 {balance}，缺 {self.shortfall}（用户 {user_id}）"
        )


class CreditsError(Exception):
    """账本使用方式错误（如对非 pending 的流水做确认）。"""


def _lock_for(user_id: str) -> threading.Lock:
    with _locks_guard:
        if user_id not in _locks:
            _locks[user_id] = threading.Lock()
        return _locks[user_id]


def _path(user_id: str) -> str:
    return os.path.join(CREDITS_DIR, f"{user_id}.json")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _new_id() -> str:
    return uuid.uuid4().hex


@dataclass
class Transaction:
    """一笔积分变动。"""

    id: str
    type: str
    amount: int                 # 正数入账，负数出账
    balance_after: int          # **必记**：变动后余额，用于对账定位
    reason: str = ""
    session_id: Optional[str] = None
    order_id: Optional[str] = None
    stage: Optional[str] = None
    # 预扣制的状态：pending → confirmed / released
    status: str = STATUS_CONFIRMED
    # 幂等键：同一个 ref 重复调用不会重复扣费
    ref: Optional[str] = None
    # 确认时实际用量超出预扣、且余额不足，缺口记在这里（不隐藏）
    shortfall: int = 0
    created_at: str = ""
    updated_at: str = ""

    def __post_init__(self):
        if not self.created_at:
            self.created_at = _now()
        if not self.updated_at:
            self.updated_at = self.created_at


def _empty(user_id: str) -> dict:
    return {
        "user_id": user_id,
        "balance": 0,
        "total_granted": 0,
        "total_consumed": 0,
        "locked": 0,
        "updated_at": "",
        "transactions": [],
    }


def _read(user_id: str) -> dict:
    path = _path(user_id)
    if not os.path.exists(path):
        return _empty(user_id)
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except (json.JSONDecodeError, OSError) as exc:
        # 账本损坏时**不降级成空账**：那等于把所有积分抹掉。
        # 这里抛出，让上层看见问题，而不是悄悄把用户的余额清零。
        raise CreditsError(f"积分账本读取失败（{path}）：{exc}") from exc
    if not isinstance(data.get("transactions"), list):
        raise CreditsError(f"积分账本格式异常（{path}）：transactions 不是列表")
    return data


def _write(user_id: str, data: dict) -> None:
    """先写临时文件再原子替换，避免写一半留下坏账本。

    **写之前一律重算派生值**。这样做是为了让"派生值过期"从根上不可能发生：
    结算流程会先追加一笔退回流水、再把原流水标成 confirmed，
    如果只在追加时重算，后面那次状态变更就不会反映到 `total_consumed` 上——
    这个 bug 真的写出来过，症状是"结算了但累计消耗还是 0"。
    把重算绑在写入上，就没有"忘了重算"这个可能了。
    """
    _recompute(data)
    path = _path(user_id)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    data["updated_at"] = _now()
    tmp = f"{path}.tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def _recompute(data: dict) -> None:
    """从流水重算派生值。

    **账本的唯一真相是流水**，`balance` / `total_granted` / `total_consumed`
    都是它的派生值，每次写入都重算一遍，于是它们不可能漂移。
    （若改成"读出来加一下再写回去"，一次并发或一次异常就会让派生值永久偏掉。）

    `total_consumed` 的口径
    ----------------------
    定义为"**真正离开账户的积分**"，而不是"所有消费流水之和"。两者不同，因为：

    - **预扣中的**还没真正花掉，钱只是被锁住 → 不算消耗
    - **已退回的**（阶段失败）根本没花 → 不算消耗
    - **预扣退还的差额**（预扣 70、实际 56）→ 只有 56 算消耗

    用恒等式表达最不容易出错：

        total_consumed = total_granted − balance − locked

    即"总共到手 − 现在可用 − 还锁着的"。这个式子不需要去关联哪笔退还是
    哪笔预扣的（靠 ref 后缀关联很脆），而是直接从余额推，天然自洽。

    这个定义正确性由单测覆盖：预扣中不计、退回的不计、退还差额要扣掉。
    """
    balance = 0
    granted = 0
    locked = 0
    for txn in data["transactions"]:
        amount = int(txn.get("amount") or 0)
        balance += amount
        if txn.get("type") in (TYPE_GRANT, TYPE_PURCHASE):
            granted += amount
        elif txn.get("type") == TYPE_CONSUME and txn.get("status") == STATUS_PENDING:
            locked += -amount          # 冻结中：还没真正花掉
    data["balance"] = balance
    data["total_granted"] = granted
    data["locked"] = locked
    data["total_consumed"] = granted - balance - locked


def _append(data: dict, txn: Transaction) -> Transaction:
    """追加一笔流水，并填上它的 `balance_after`。

    `balance_after` 必须在这里就填好——它是事后定位"哪一笔开始错"的唯一线索。
    按已有流水累加得出（而不是读账户余额），这样即使账户余额字段被写坏，
    流水自身的链条仍然是自洽的，对账时能看出是哪一层出的问题。
    """
    running = sum(int(t.get("amount") or 0) for t in data["transactions"])
    txn.balance_after = running + txn.amount
    data["transactions"].append(asdict(txn))
    return txn


def verify(user_id: str) -> dict:
    """对账：检查账本自洽。返回问题列表，空列表即一切正常。

    检查两件事：
    1. `sum(amount) == balance`（本模块的核心不变式）
    2. 每笔流水的 `balance_after` 等于它及之前所有流水的累计
    """
    data = _read(user_id)
    problems: list[str] = []
    running = 0
    for i, txn in enumerate(data["transactions"]):
        running += int(txn.get("amount") or 0)
        if int(txn.get("balance_after", 0)) != running:
            problems.append(
                f"第 {i + 1} 笔流水 {txn.get('id', '?')[:8]} 的 balance_after="
                f"{txn.get('balance_after')}，按累加应为 {running}"
            )
    if running != int(data.get("balance", 0)):
        problems.append(f"流水累加 {running} 与账户余额 {data.get('balance')} 不一致")
    if running < 0:
        problems.append(f"余额为负（{running}），账本被写坏")
    return {"user_id": user_id, "balance": data.get("balance", 0), "problems": problems}


def get_account(user_id: str = LOCAL_USER) -> dict:
    """账户概览（不含流水明细）。"""
    data = _read(user_id)
    return {
        "user_id": data["user_id"],
        # balance 是**可用**余额。冻结状态不另开字段，由 pending 流水表达。
        "balance": data["balance"],
        "locked": data.get("locked", 0),
        "total_granted": data["total_granted"],
        "total_consumed": data["total_consumed"],
        "transaction_count": len(data["transactions"]),
        "pending_count": len([t for t in data["transactions"]
                              if t.get("status") == STATUS_PENDING]),
        "updated_at": data.get("updated_at", ""),
    }


def get_ledger(
    user_id: str = LOCAL_USER, limit: int = 0, session_id: Optional[str] = None
) -> list[dict]:
    """流水明细，最新的在前。"""
    data = _read(user_id)
    items = list(reversed(data["transactions"]))
    if session_id:
        items = [t for t in items if t.get("session_id") == session_id]
    if limit > 0:
        items = items[:limit]
    return items


def _find_by_ref(data: dict, ref: str) -> Optional[dict]:
    for txn in reversed(data["transactions"]):
        if txn.get("ref") == ref:
            return txn
    return None


def grant(
    user_id: str,
    credits: int,
    reason: str,
    *,
    type_: str = TYPE_GRANT,
    ref: Optional[str] = None,
    order_id: Optional[str] = None,
) -> dict:
    """入账（赠送 / 购买）。按 `ref` 幂等。"""
    if credits <= 0:
        raise CreditsError(f"入账积分数必须为正，收到 {credits}")
    with _lock_for(user_id):
        data = _read(user_id)
        if ref:
            existing = _find_by_ref(data, ref)
            if existing is not None:
                return existing          # 幂等：同一笔赠送只发一次
        txn = Transaction(
            id=_new_id(), type=type_, amount=credits, balance_after=0,
            reason=reason, status=STATUS_CONFIRMED, ref=ref, order_id=order_id,
        )
        _append(data, txn)
        _write(user_id, data)
        logger.info("积分入账 user=%s +%d（%s）→ 余额 %d", user_id, credits, reason, data["balance"])
        return asdict(txn)


def grant_signup_bonus(user_id: str) -> Optional[dict]:
    """注册一次性赠送。靠固定 ref 保证只发一次。"""
    return grant(
        user_id, SIGNUP_GRANT, "注册赠送",
        ref=f"signup:{user_id}",
    )


def reserve(
    user_id: str,
    credits: int,
    reason: str,
    *,
    ref: str,
    session_id: Optional[str] = None,
    stage: Optional[str] = None,
) -> dict:
    """预扣。余额立即减少，流水状态为 pending。

    `ref` 必填且全局唯一（建议用 `"{session_id}:{stage}"`）：
    同一个 ref 重复调用返回第一次的结果，**不会重复扣费**。
    这一条是防"重试/连点导致重复扣费"的关键。
    """
    if credits <= 0:
        raise CreditsError(f"预扣积分数必须为正，收到 {credits}")
    if not ref:
        raise CreditsError("预扣必须提供 ref（幂等键）")

    with _lock_for(user_id):
        data = _read(user_id)
        existing = _find_by_ref(data, ref)
        if existing is not None:
            logger.info("预扣命中已有记录（幂等）ref=%s → 不重复扣费", ref)
            return existing

        balance = int(data["balance"])
        if balance < credits:
            raise InsufficientCredits(required=credits, balance=balance, user_id=user_id)

        txn = Transaction(
            id=_new_id(), type=TYPE_CONSUME, amount=-credits, balance_after=0,
            reason=reason, session_id=session_id, stage=stage,
            status=STATUS_PENDING, ref=ref,
        )
        _append(data, txn)
        _write(user_id, data)
        logger.info(
            "积分预扣 user=%s -%d（%s）→ 余额 %d", user_id, credits, reason, data["balance"]
        )
        return asdict(txn)


def _settle_locked(data: dict, txn: dict, actual_credits: int) -> dict:
    """在已持锁的前提下把一笔预扣结算到实际用量。"""
    reserved = -int(txn["amount"])
    if actual_credits < 0:
        raise CreditsError(f"实际积分不能为负，收到 {actual_credits}")
    diff = actual_credits - reserved

    if diff == 0:
        txn["status"] = STATUS_CONFIRMED
        txn["updated_at"] = _now()
        return txn

    if diff < 0:
        # 实际比预扣少 → 退回差额
        _append(data, Transaction(
            id=_new_id(), type=TYPE_REFUND, amount=-diff, balance_after=0,
            reason=f"预扣退还（{txn.get('reason', '')}）",
            session_id=txn.get("session_id"), stage=txn.get("stage"),
            status=STATUS_CONFIRMED, ref=f"{txn.get('ref')}:refund",
        ))
        txn["status"] = STATUS_CONFIRMED
        txn["updated_at"] = _now()
        return txn

    # 实际比预扣多 → 补扣。余额不够时扣到 0，并把缺口记下来（不隐藏）
    balance = int(data["balance"])
    charge = min(diff, max(balance, 0))
    shortfall = diff - charge
    if charge:
        _append(data, Transaction(
            id=_new_id(), type=TYPE_CONSUME, amount=-charge, balance_after=0,
            reason=f"预扣补扣（{txn.get('reason', '')}）",
            session_id=txn.get("session_id"), stage=txn.get("stage"),
            status=STATUS_CONFIRMED, ref=f"{txn.get('ref')}:extra",
        ))
    txn["status"] = STATUS_CONFIRMED
    txn["shortfall"] = shortfall
    txn["updated_at"] = _now()
    if shortfall:
        logger.warning(
            "积分缺口 %d：实际用量超出预扣且余额不足（ref=%s）。"
            "缺口已记在流水 shortfall 字段，未隐藏。",
            shortfall, txn.get("ref"),
        )
    return txn


def settle(reservation_ref: str, actual_credits: int, user_id: str = LOCAL_USER) -> dict:
    """确认一笔预扣，并把金额调整到**实际用量**。

    为什么不是简单的"确认"：预扣是估算，实际用量几乎必然不同
    （视频按 tokens 计费，同一个模型不同任务都能差 2 倍）。
    所以确认时必须结算差额，否则不是多扣就是少扣。

    对已结算过的流水重复调用是安全的（幂等）。
    """
    with _lock_for(user_id):
        data = _read(user_id)
        txn = _find_by_ref(data, reservation_ref)
        if txn is None:
            raise CreditsError(f"找不到预扣记录：{reservation_ref}")
        if txn["type"] != TYPE_CONSUME:
            raise CreditsError(f"ref={reservation_ref} 不是消费流水，无法确认")
        if txn.get("status") != STATUS_PENDING:
            return txn          # 幂等：已经结算过
        result = _settle_locked(data, txn, actual_credits)
        _write(user_id, data)
        logger.info(
            "积分结算 ref=%s：预扣 %d → 实际 %d，余额 %d",
            reservation_ref, -result["amount"], actual_credits, data["balance"],
        )
        return result


def release(reservation_ref: str, user_id: str = LOCAL_USER, reason: str = "") -> dict:
    """退回一笔预扣（阶段失败或取消）。全额返还，原流水标记为 released。"""
    with _lock_for(user_id):
        data = _read(user_id)
        txn = _find_by_ref(data, reservation_ref)
        if txn is None:
            raise CreditsError(f"找不到预扣记录：{reservation_ref}")
        if txn.get("status") == STATUS_RELEASED:
            return txn          # 幂等
        if txn.get("status") != STATUS_PENDING:
            raise CreditsError(
                f"ref={reservation_ref} 已结算（{txn.get('status')}），不能再退回"
            )
        amount = -int(txn["amount"])
        _append(data, Transaction(
            id=_new_id(), type=TYPE_REFUND, amount=amount, balance_after=0,
            reason=reason or f"预扣退回（{txn.get('reason', '')}）",
            session_id=txn.get("session_id"), stage=txn.get("stage"),
            status=STATUS_CONFIRMED, ref=f"{txn.get('ref')}:release",
        ))
        txn["status"] = STATUS_RELEASED
        txn["updated_at"] = _now()
        _write(user_id, data)
        logger.info("积分退回 ref=%s +%d → 余额 %d", reservation_ref, amount, data["balance"])
        return txn


def pending_reservations(user_id: str = LOCAL_USER) -> list[dict]:
    """查所有仍在预扣中的流水。用于排查"钱扣了但阶段没跑完"的悬挂记录。"""
    return [t for t in _read(user_id)["transactions"] if t.get("status") == STATUS_PENDING]


def credits_for_cost(cost_yuan: float, k: float = DEFAULT_K) -> int:
    """成本（元）→ 积分。走 `models/credits.py`，与定价表同一套公式。"""
    return credits_for(cost_yuan, k)
