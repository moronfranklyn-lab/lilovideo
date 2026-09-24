"""阶段积分预估。

用途：阶段开始前**预扣**多少积分。

为什么需要预估，以及预估不准会怎样
----------------------------------
积分走「预扣 → 确认 / 退回」（规则见《积分与会员模型.md》），
所以阶段开始前必须先拿出一个数来扣。这个数不可能精确——同一个视频模型
按 tokens 计费，不同任务的用量能差 2 倍。于是：

- **估多了**：用户余额被多占，可能明明够用却被挡在门外
- **估少了**：结算时要补扣，余额不够就产生缺口（会被记下来，但体验差）

所以本模块的原则是「**能算准的算准，算不准的用实测值兜底**」：

- 视频阶段：镜头数与所选模型都已知 → **按档位精算**（最准，也最重要，
  它占一条成片成本的约 80%）
- 图片/文本阶段：数量与 token 量都不确定 → 用**真实预跑的实测值**兜底
- 后期剪辑：纯 ffmpeg，无模型调用 → 0

无论估多少，**结算都会按实际用量纠正**，所以这里的误差只影响
"预扣占用了多少余额"，不会影响最终扣了多少钱。
"""

from __future__ import annotations

import logging
from typing import Optional

from models.credits import DEFAULT_K, credits_for
from models.cost import estimate_video_cost

logger = logging.getLogger(__name__)

# 兜底预估（元）。来源：2026-09-22 真实预跑的实测值，见《积分与会员模型.md》§1 与 §4。
#
# 用实测值而不是拍脑袋的数，是因为这些阶段的成本虽然小（合计约 ¥2），
# 但如果估成 0，用户就会在余额不足时走进阶段、最后产生缺口。
STAGE_FALLBACK_COST_YUAN: dict[str, float] = {
    "script_generation": 0.72,      # 剧本生成（LLM）
    "character_design": 1.20,       # 角色图 × 3 + 场景图 × 1 + 图片评估
    "storyboard": 0.94,             # 分镜规划（LLM）
    "reference_generation": 1.50,   # 参考图 + 图片评估
    "video_generation": 4.97,       # 兜底：按一个 720P 片段算
    "post_production": 0.0,         # 后期剪辑只调 ffmpeg，不产生模型成本
}

# 单个视频片段的默认时长（秒）。与 video_agent.PREVIEW_CLIP_SECONDS 对应，
# 正式生成也是按这个长度切片。
DEFAULT_CLIP_SECONDS = 5.0


def estimate_video_stage_credits(
    segment_count: int,
    model: Optional[str],
    resolution: Optional[str] = None,
    seconds: float = DEFAULT_CLIP_SECONDS,
    k: float = DEFAULT_K,
) -> int:
    """视频阶段的预扣积分：镜头数 × 单片段积分。

    **镜头数为 0 时按 1 个片段预扣，而不是 0。**

    为什么：`segment_count == 0` 有两种可能——分镜确实是空的，或者
    **我们没能从会话状态里解析出镜头数**（分镜结构变过、字段缺失等）。
    后者会让预扣整个失效，用户毫无阻拦地走进一个几分钟、上百积分的阶段。
    两者无法在这里区分，所以按"至少有一个片段"处理：
    宁可多占一点余额（结算会立刻退还），也不要放行一个付不起的阶段。
    """
    count = segment_count if segment_count > 0 else 1
    if not model:
        logger.warning("视频阶段预估缺少模型名，退回兜底值")
        return credits_for(STAGE_FALLBACK_COST_YUAN["video_generation"], k) * count

    result = estimate_video_cost(model, seconds, resolution=resolution or "720P")
    if result is None:
        logger.warning(
            "视频阶段预估：模型 %s（%s）算不出单价，退回兜底值",
            model, resolution,
        )
        per_clip = credits_for(STAGE_FALLBACK_COST_YUAN["video_generation"], k)
    else:
        per_clip = credits_for(result.amount, k)
    return per_clip * count


def estimate_stage_credits(
    stage: str,
    *,
    segment_count: int = 0,
    model: Optional[str] = None,
    resolution: Optional[str] = None,
    seconds: float = DEFAULT_CLIP_SECONDS,
    k: float = DEFAULT_K,
) -> int:
    """估算某阶段的预扣积分。

    `segment_count` / `model` / `resolution` 只有视频阶段用得上，其余阶段忽略。
    """
    if stage == "video_generation":
        return estimate_video_stage_credits(
            segment_count, model, resolution, seconds, k
        )
    if stage == "post_production":
        return 0
    cost = STAGE_FALLBACK_COST_YUAN.get(stage)
    if cost is None:
        # 没登记的阶段：给一个保守的小额，而不是 0。
        # 0 会让预扣形同虚设；用最小档位（10 积分）作为下限。
        logger.info("阶段 %s 没有预估配置，使用最小预扣额", stage)
        return 10
    return credits_for(cost, k)
