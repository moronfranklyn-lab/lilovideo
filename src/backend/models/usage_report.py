"""从模型 API 的响应体里取出用量，并交给成本层记账。

为什么单独一个模块
------------------
三种客户端都要记账，而它们的响应结构大同小异：

- DashScope 的 LLM 与 VLM（`Generation` / `MultiModalConversation`）
- OpenAI 兼容接口（DeepSeek 客户端用的就是它，方舟也提供兼容接口）

这段"韧性取值"的逻辑（字段可能在对象上也可能在 dict 里、
可能叫 input_tokens 也可能叫 prompt_tokens）如果复制多份，
迟早各自漂移，然后各处的成本数字开始不一致。

**这里的取值必须宽容，但失败必须说出来。** 取不到用量时记 warning 日志——
成本算不出来是可见的损失（账少了），静默吞掉最危险。
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from models.cost import Usage
from models.cost_store import report_usage

logger = logging.getLogger(__name__)


def _pick(source: Any, *keys: str) -> Optional[int]:
    """从对象或 dict 里按多个候选字段名取值，返回第一个非空整数。"""
    if source is None:
        return None
    for key in keys:
        value = source.get(key) if isinstance(source, dict) else getattr(source, key, None)
        if value is None:
            continue
        try:
            return int(value)
        except (TypeError, ValueError):
            continue
    return None


def report_chat_usage(model: str, response: Any) -> Optional[int]:
    """记录一次对话式补全的 tokens 用量。

    返回总 tokens；取不到时返回 None 并记 warning。

    字段名在不同平台/版本上不完全一致，两种都认：

    - DashScope / qwen 系：``input_tokens`` / ``output_tokens``
    - OpenAI 兼容接口（DeepSeek、方舟）：``prompt_tokens`` / ``completion_tokens``

    **注意推理模型**：DeepSeek V4.1 Flash 这类模型会把 tokens 花在
    ``reasoning_tokens`` 上，它已包含在 ``completion_tokens`` 里，
    所以按 completion_tokens 计费是对的，不要另外再加。

    **调用时机很重要**：应在"API 调用成功返回"之后立刻调用，
    **不要等到确认 content 可用才记**。否则一旦内容为空触发重试，
    那次已经花掉的钱就没人记了。
    """
    usage = getattr(response, "usage", None)
    if usage is None and isinstance(response, dict):
        usage = response.get("usage")

    input_tokens = _pick(usage, "input_tokens", "prompt_tokens") or 0
    output_tokens = _pick(usage, "output_tokens", "completion_tokens") or 0

    if not input_tokens and not output_tokens:
        logger.warning(
            "响应里没有可用的 token 用量，本次成本无法计算: model=%s usage=%r",
            model, usage,
        )
        return None

    report_usage(Usage(
        model_id=model,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
    ))
    return input_tokens + output_tokens
