"""pytest 公共夹具。"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from models.pricing import PRICING, PriceSpec  # noqa: E402


@pytest.fixture
def unverified_video_spec(monkeypatch):
    """注入一条**故意保持未核实**的视频定价，用于测试"未核实"分支。

    为什么不直接借用注册表里的真实模型
    ----------------------------------
    真实模型的核实状态会随核实工作变化，拿它当夹具等于把测试焊在被测数据上。
    本项目已经踩过一次：早先 `doubao-seedance-2-0-fast` 尚未核实，
    测试就用它当"未核实"的样本；后来该档价格核实完成、`verified` 改成 True，
    两个测试立刻变红——而它们想验证的逻辑从头到尾都是对的。

    夹具必须自己造，不能依赖被测系统的当前状态。
    """
    spec = PriceSpec(
        model_id="test-only-unverified-video",
        provider="ark",
        billing="per_token",
        output_per_million=37.0,
        verified=False,
        source="（测试夹具，不是真实定价）",
        note="测试夹具：故意保持未核实状态，永不出现在真实注册表里",
    )
    monkeypatch.setitem(PRICING, spec.model_id, spec)
    return spec
