"""样片模式（先出样片再批量生成）的测试。

为什么要有这个模式
------------------
视频按时长计费（Seedance 2.0 约 1 元/秒）。整片批量生成后才发现风格不对，
返工成本极高。先用 1 个片段、5 秒验证效果，只需约 5 元。

这里测的是**决策逻辑**（选哪些片段、用什么时长、回报什么状态），
不触发真实模型调用。
"""

import os
import sys
from typing import Any, Dict, List, Optional

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.agents.video_agent import PREVIEW_CLIP_SECONDS, VideoDirectorAgent  # noqa: E402


class _StubAgent(VideoDirectorAgent):
    """替换掉全部外部交互，只保留目标选择与时长决策逻辑。"""

    def __init__(self, segments: List[Dict[str, Any]]):
        super().__init__()
        self._segments = segments
        self.generated: List[tuple[str, int]] = []
        self.reported: List[str] = []

    # ── 屏蔽外部依赖 ──────────────────────────────────────────────
    def _merge_session_params(self, input_data):
        return input_data

    def _session_meta(self, input_data):
        return {}

    def _session_artifacts(self, input_data):
        return {
            "storyboard": {"episodes": [{"segments": self._segments}]},
            "reference_generation": {"scenes": []},
            "character_design": {},
            "video_generation": {"clips": []},
        }

    def _select_video_model(self, input_data, session_meta):
        return "first_frame", "test-model"

    def _get_style_prompt(self, style):
        return ""

    def _assemble_prompt(self, seg, style_prompt, character_art, video_data=None):
        return f"prompt-{seg['segment_id']}"

    def _get_reference_image(self, sid, seg_id, scene_map):
        return ""

    def _get_next_reference_image(self, sid, seg_index, segments, scene_map):
        return None

    def _list_versions(self, sid, segment_id):
        return []

    def _update_session_video_data(self, sid, segments, style_prompt):
        return None

    def _build_payload(self, sid, segments, video_clips=None):
        return {"payload": {"session_id": sid, "clips": []}, "stage_completed": True}

    def _report_progress(self, phase, step, percent, data=None):
        self.reported.append(f"{phase}:{step}")

    def _generate_one(self, sid, segment_id, prompt, img_path, model, duration,
                      *args, **kwargs):
        """记录实际请求的片段与时长，不真的调模型。"""
        self.generated.append((segment_id, duration))
        return None, f"/fake/{segment_id}.mp4"


def _segments(n: int) -> List[Dict[str, Any]]:
    return [
        {"segment_id": f"seg_{i:02d}", "total_duration": 10, "episode_number": 1,
         "segment_number": i}
        for i in range(1, n + 1)
    ]


def _run(agent, intervention: Optional[Dict] = None):
    import asyncio
    return asyncio.run(agent.process({"session_id": "s"}, intervention))


class TestPreviewMode:
    def test_样片模式只生成第一个片段(self):
        agent = _StubAgent(_segments(6))
        result = _run(agent, {"generate_preview": True})

        assert len(agent.generated) == 1
        assert agent.generated[0][0] == "seg_01"

    def test_样片时长用固定值而非分镜时长(self):
        """样片必须短，否则省不下钱。分镜写 10 秒，样片应是 5 秒。"""
        agent = _StubAgent(_segments(4))
        _run(agent, {"generate_preview": True})

        seg_id, duration = agent.generated[0]
        assert duration == PREVIEW_CLIP_SECONDS
        assert duration != 10

    def test_回报剩余片段数(self):
        agent = _StubAgent(_segments(6))
        result = _run(agent, {"generate_preview": True})

        p = result["preview"]
        assert p["preview_only"] is True
        assert p["generated"] == 1
        assert p["total"] == 6
        assert p["remaining"] == 5

    def test_样片模式下索引仍指向原始列表(self):
        """回归：首尾帧模式靠索引取下一帧的参考图，索引用错会取错尾帧。"""
        agent = _StubAgent(_segments(4))
        captured = {}
        original = agent._get_next_reference_image

        def spy(sid, seg_index, segments, scene_map):
            captured["index"] = seg_index
            captured["segments_len"] = len(segments)
            return original(sid, seg_index, segments, scene_map)

        agent._get_next_reference_image = spy
        _run(agent, {"generate_preview": True})

        assert captured["index"] == 0
        # 关键：传入的应是完整列表，不是被裁剪成 1 个的列表
        assert captured["segments_len"] == 4


class TestFullMode:
    def test_不带介入参数时生成全部片段(self):
        agent = _StubAgent(_segments(4))
        _run(agent, None)

        assert len(agent.generated) == 4
        assert [g[0] for g in agent.generated] == ["seg_01", "seg_02", "seg_03", "seg_04"]

    def test_全量模式用分镜自己的时长(self):
        agent = _StubAgent(_segments(3))
        _run(agent, None)

        assert all(duration == 10 for _, duration in agent.generated)

    def test_全量模式回报无剩余(self):
        agent = _StubAgent(_segments(3))
        result = _run(agent, None)

        p = result["preview"]
        assert p["preview_only"] is False
        assert p["remaining"] == 0
        assert p["generated"] == p["total"] == 3

    def test_用户可选跳过预览(self):
        """产品决策：默认先预览，但允许用户跳过。不带 generate_preview 即为跳过。"""
        agent = _StubAgent(_segments(5))
        result = _run(agent, {})

        assert result["preview"]["preview_only"] is False
        assert len(agent.generated) == 5

    def test_generate_preview_为假时不进预览(self):
        agent = _StubAgent(_segments(3))
        result = _run(agent, {"generate_preview": False})

        assert result["preview"]["preview_only"] is False
        assert len(agent.generated) == 3


class TestPreviewCost:
    def test_样片相比全片显著省成本(self):
        """样片的意义就在省成本，用秒数比来表达。"""
        n_segments = 6
        normal_seconds = n_segments * 10          # 60 秒
        preview_seconds = PREVIEW_CLIP_SECONDS    # 5 秒

        # 样片成本应低于全片的 1/5，否则这个模式没有意义
        assert preview_seconds < normal_seconds / 5
