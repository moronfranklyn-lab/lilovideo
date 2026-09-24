"""样片模式的端到端测试：验证介入参数能穿过 orchestrator 到达 agent。

背景
----
agent 内部单测通过，不代表参数能穿过编排层。orchestrator 在
`_is_background_item_regeneration` 判定为「按项重做」时会走合并分支，
该分支会重建 payload，可能丢掉额外字段。

本测试用真实的判定方法验证参数通路，不触发真实模型调用。
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.orchestrator import WorkflowEngine, WorkflowStage  # noqa: E402

VIDEO = WorkflowStage.VIDEO_GENERATION


class TestInterventionReachability:
    def test_generate_preview_不被判为按项重做(self):
        """关键：generate_preview 必须走正常执行路径。

        若被判为按项重做，payload 会被合并逻辑重建，preview 标记可能丢失。
        """
        assert WorkflowEngine._is_background_item_regeneration(
            VIDEO, {"generate_preview": True}
        ) is False

    def test_regenerate_clips_仍判为按项重做(self):
        """回归：原有的单镜头重做不能被破坏。"""
        assert WorkflowEngine._is_background_item_regeneration(
            VIDEO, {"regenerate_clips": ["seg_01"]}
        ) is True

    def test_两种介入同时出现时按项重做优先(self):
        """同时传预览标记与重做列表时，保持原有按项重做行为不变。"""
        assert WorkflowEngine._is_background_item_regeneration(
            VIDEO, {"regenerate_clips": ["seg_01"], "generate_preview": True}
        ) is True

    def test_重做目标集合不混入预览标记(self):
        """按项重做的目标集合不应把预览标记当成片段 ID。"""
        targets = WorkflowEngine._background_regeneration_targets(
            VIDEO, {"regenerate_clips": ["seg_01"], "generate_preview": True}
        )
        assert targets.get("clips") == {"seg_01"}

    def test_空介入不判为按项重做(self):
        assert WorkflowEngine._is_background_item_regeneration(VIDEO, None) is False
        assert WorkflowEngine._is_background_item_regeneration(VIDEO, {}) is False
