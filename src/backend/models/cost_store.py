"""会话成本记录。

把每一次模型调用的成本累计到会话文件，支撑两件事：
1. **实时可见**：用户能看到当前已花费多少
2. **可归因**：每一步花了多少、花在哪个模型上

存储形态
--------
写在会话目录下的独立文件 `cost.json`，**不修改 orchestrator 持有的会话文件**。
这样成本记录与工作流状态解耦：即使成本写入失败，也不会影响生成流程。

文件结构：
```json
{
  "session_id": "...",
  "records": [
    {"stage": "script_generation", "model_id": "qwen-max", "amount": 0.12,
     "verified": true, "breakdown": "...", "at": "2026-09-22T..."}
  ],
  "updated_at": "..."
}
```

金额一律为人民币元。合计由记录累加得出，不单独存字段，避免不一致。
"""

from __future__ import annotations

import contextvars
import json
import logging
import os
import threading
from concurrent.futures import Executor
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Iterator, Optional, TypeVar

from config import BASE_DIR
from models.cost import CostResult, Usage, compute_cost

logger = logging.getLogger(__name__)

# 会话目录与 orchestrator 保持一致。
#
# 可用环境变量 `LILOVIDEO_SESSIONS_DIR` 覆盖：这样一次性工具与测试就能把账
# 写到临时目录，而不是污染真实项目的账本。
# （起因：验证脚本的 dry-run 曾经误删真实记录，给它一个可重定向的落点
#   之后，这类工具就不必碰真实数据了。）
SESSIONS_DIR = os.environ.get("LILOVIDEO_SESSIONS_DIR") or os.path.join(
    BASE_DIR, "code", "data", "sessions"
)

# 同一进程内对同一会话文件的并发写保护
_locks: dict[str, threading.Lock] = {}
_locks_guard = threading.Lock()


def _lock_for(session_id: str) -> threading.Lock:
    with _locks_guard:
        if session_id not in _locks:
            _locks[session_id] = threading.Lock()
        return _locks[session_id]


def _cost_path(session_id: str) -> str:
    return os.path.join(SESSIONS_DIR, f"{session_id}.cost.json")


@dataclass
class CostRecord:
    """一次模型调用的成本记录。"""

    stage: str
    model_id: str
    amount: float
    billing: str
    verified: bool
    breakdown: str
    at: str = ""
    # 保留原始用量，便于日后核对账单或调整定价后重算
    usage: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        if not self.at:
            self.at = datetime.now(timezone.utc).isoformat()


def _read(session_id: str) -> dict:
    path = _cost_path(session_id)
    if not os.path.exists(path):
        return {"session_id": session_id, "records": [], "updated_at": ""}
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data.get("records"), list):
            data["records"] = []
        return data
    except (json.JSONDecodeError, OSError) as exc:
        # 文件损坏时不抛异常给主流程，降级为空记录并告警
        logger.warning("成本文件读取失败 %s: %s", path, exc)
        return {"session_id": session_id, "records": [], "updated_at": ""}


def _write(session_id: str, data: dict) -> None:
    path = _cost_path(session_id)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    data["updated_at"] = datetime.now(timezone.utc).isoformat()
    tmp = f"{path}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def record_usage(
    session_id: str,
    stage: str,
    usage: Usage,
    *,
    raise_on_error: bool = False,
) -> Optional[CostResult]:
    """记录一次调用的用量与成本。

    返回计算出的成本；无法计算时返回 None 并**不写记录**——
    "成本未知"不应该在流水里留下一条金额为 0 的假记录。

    默认吞掉异常：成本记录失败不应中断生成流程。
    """
    try:
        result = compute_cost(usage)
        if result is None:
            logger.info(
                "成本无法计算（未登记定价或无用量），跳过记录: model=%s stage=%s",
                usage.model_id, stage,
            )
            return None

        rec = CostRecord(
            stage=stage,
            model_id=result.model_id,
            amount=result.amount,
            billing=result.billing,
            verified=result.verified,
            breakdown=result.breakdown,
            usage=asdict(usage),
        )

        with _lock_for(session_id):
            data = _read(session_id)
            data["records"].append(asdict(rec))
            _write(session_id, data)

        return result
    except Exception as exc:  # noqa: BLE001 - 成本记录不得影响主流程
        logger.warning("成本记录失败 session=%s stage=%s: %s", session_id, stage, exc)
        if raise_on_error:
            raise
        return None


def get_summary(session_id: str) -> dict:
    """汇总一个会话的成本。

    返回结构包含：
    - `total`：合计金额
    - `has_unverified`：是否含未核实定价的条目（界面据此提示"金额可能不准"）
    - `has_unknown`：是否存在无法计算的调用（界面据此提示"部分成本未知"）
    - `by_stage`：按阶段分组的小计
    - `by_model`：按模型分组的小计
    """
    data = _read(session_id)
    records = data.get("records", [])

    total = 0.0
    by_stage: dict[str, float] = {}
    by_model: dict[str, float] = {}
    has_unverified = False

    for r in records:
        amount = float(r.get("amount") or 0.0)
        total += amount
        stage = r.get("stage") or "unknown"
        model = r.get("model_id") or "unknown"
        by_stage[stage] = round(by_stage.get(stage, 0.0) + amount, 6)
        by_model[model] = round(by_model.get(model, 0.0) + amount, 6)
        if not r.get("verified", False):
            has_unverified = True

    return {
        "session_id": session_id,
        "currency": "CNY",
        "total": round(total, 6),
        "call_count": len(records),
        # 有记录但全部无法核实，或没有任何记录，都算"未知"来源
        "has_unverified": has_unverified,
        "has_unknown": len(records) == 0,
        "by_stage": by_stage,
        "by_model": by_model,
        "records": records,
        "updated_at": data.get("updated_at", ""),
    }


def clear(session_id: str) -> None:
    """清空一个会话的成本记录。用于重跑项目时重新计费。"""
    with _lock_for(session_id):
        path = _cost_path(session_id)
        if os.path.exists(path):
            os.remove(path)


# ── 计费上下文：让客户端不传 session_id 也能记账 ────────────────────────
#
# 背景（这是一次真实事故的修法）
# ----------------------------
# `record_usage()` 写好后**整整一轮开发都没被调用过**：模块齐全、40 个测试全绿，
# 但真实项目一条成本都没记下（`code/data/sessions/*.cost.json` 一个都没有），
# 成本接口对真实会话永远返回 0。
#
# 根因是"记账要传 session_id 和 stage，但模型调用点根本拿不到它们"。
# 模型调用散布在 8 个地方，其中 6 个在线程池的工作线程里。
#
# 所以这里用上下文变量：orchestrator 在阶段开始时开一个作用域，
# 客户端只需 `report_usage(usage)` 一句话，不用改任何签名。

# 当前计费上下文：(session_id, stage)
_scope: contextvars.ContextVar[Optional[tuple[str, str]]] = contextvars.ContextVar(
    "lilovideo_cost_scope", default=None
)


@contextmanager
def cost_scope(session_id: str, stage: str) -> Iterator[None]:
    """把一段代码标记为「正在为某会话的某阶段花钱」。"""
    token = _scope.set((session_id, stage))
    try:
        yield
    finally:
        _scope.reset(token)


def current_scope() -> Optional[tuple[str, str]]:
    """取当前计费上下文，没有则返回 None。便于测试与排查。"""
    return _scope.get()


def report_usage(usage: Usage, *, stage: Optional[str] = None) -> Optional[CostResult]:
    """把一次模型调用的用量记到当前计费上下文。

    **没有上下文时静默跳过**：沙盒里的独立调用本来就不属于任何会话，
    既不该报错，也不该在日志里刷警告。
    """
    scope = _scope.get()
    if scope is None:
        logger.debug("无计费上下文，跳过成本记录: model=%s", usage.model_id)
        return None
    session_id, scoped_stage = scope
    return record_usage(session_id, stage or scoped_stage, usage)


_T = TypeVar("_T")


def submit_with_cost_context(executor: Executor, fn: Callable[..., _T], *args: Any, **kwargs: Any):
    """在线程池里提交任务，并把当前计费上下文带进去。

    **必须用它，不要直接用 `executor.submit`。**

    Python 的 `ThreadPoolExecutor` **不会**自动复制 contextvars
    （`asyncio.to_thread` 才会）。直接 submit 的后果是：工作线程里
    `report_usage` 看不到会话，成本**静默丢失**——不报错，也不写日志，
    只是账少了。这正是最难发现的那类 bug。

    用法：

        fut = submit_with_cost_context(executor, worker, arg1, arg2)
    """
    ctx = contextvars.copy_context()
    return executor.submit(ctx.run, fn, *args, **kwargs)
