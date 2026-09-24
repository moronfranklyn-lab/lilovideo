"""会话成本记录的单元测试。

覆盖三类风险：
1. 累计是否正确
2. 无法计算的调用是否被正确跳过（不能写入金额为 0 的假记录）
3. 存储异常是否被隔离，不影响主流程
"""

import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from models import cost_store  # noqa: E402
from models.cost import Usage  # noqa: E402


@pytest.fixture(autouse=True)
def isolated_dir(tmp_path, monkeypatch):
    """把成本目录指向临时目录，避免污染真实会话数据。"""
    monkeypatch.setattr(cost_store, "SESSIONS_DIR", str(tmp_path))
    yield tmp_path


class TestRecordAndSummary:
    def test_空会话返回零合计与未知标记(self):
        s = cost_store.get_summary("新会话")
        assert s["total"] == 0
        assert s["call_count"] == 0
        # 没有任何记录时，必须标记为"未知"而不是"免费"
        assert s["has_unknown"] is True
        assert s["currency"] == "CNY"

    def test_记录一次调用后可查询(self):
        cost_store.record_usage(
            "s1", "script_generation",
            Usage(model_id="qwen-max", input_tokens=1_000_000, output_tokens=0),
        )
        s = cost_store.get_summary("s1")
        assert s["call_count"] == 1
        assert s["total"] == pytest.approx(2.4)
        assert s["has_unknown"] is False

    def test_多次调用累计正确(self):
        cost_store.record_usage("s2", "script_generation",
                                Usage(model_id="qwen-max", input_tokens=1_000_000))
        cost_store.record_usage("s2", "character_design",
                                Usage(model_id="qwen3.7-plus", input_tokens=1_000_000))
        s = cost_store.get_summary("s2")
        assert s["call_count"] == 2
        # 2.4 (qwen-max 输入) + 2.0 (qwen3.7-plus 输入) = 4.4
        assert s["total"] == pytest.approx(4.4)
        assert s["by_stage"]["script_generation"] == pytest.approx(2.4)
        assert s["by_stage"]["character_design"] == pytest.approx(2.0)
        assert s["by_model"]["qwen-max"] == pytest.approx(2.4)

    def test_视频按tokens记录(self):
        cost_store.record_usage("s3", "video_generation",
                                Usage(model_id="doubao-seedance-2-0-260128", output_tokens=308_880))
        s = cost_store.get_summary("s3")
        assert s["total"] == pytest.approx(14.21, abs=0.01)

    def test_未核实定价会打标记(self, unverified_video_spec):
        cost_store.record_usage("s4", "video_generation",
                                Usage(model_id=unverified_video_spec.model_id, input_tokens=1_000_000))
        s = cost_store.get_summary("s4")
        # 能算，但必须提示用户金额不可靠
        assert s["has_unverified"] is True


class TestUncomputableHandling:
    def test_未知模型不写入假记录(self):
        """关键：算不出来时不能往流水里塞一条金额 0 的记录。"""
        result = cost_store.record_usage("s5", "script_generation",
                                         Usage(model_id="未知模型", input_tokens=1000))
        assert result is None
        s = cost_store.get_summary("s5")
        assert s["call_count"] == 0
        assert s["total"] == 0

    def test_零用量不写入记录(self):
        result = cost_store.record_usage("s6", "script_generation", Usage(model_id="qwen-max"))
        assert result is None
        assert cost_store.get_summary("s6")["call_count"] == 0


class TestRobustness:
    def test_文件损坏时降级为空而不抛异常(self, isolated_dir):
        path = os.path.join(str(isolated_dir), "broken.cost.json")
        with open(path, "w", encoding="utf-8") as f:
            f.write("{ 这不是合法 JSON")

        s = cost_store.get_summary("broken")
        assert s["total"] == 0
        assert s["call_count"] == 0

    def test_成本目录不可写时不中断主流程(self, monkeypatch):
        """成本记录失败必须被吞掉，不能影响生成流程。"""
        def boom(*a, **k):
            raise OSError("模拟磁盘写入失败")

        monkeypatch.setattr(cost_store, "_write", boom)
        result = cost_store.record_usage(
            "s7", "script_generation",
            Usage(model_id="qwen-max", input_tokens=1_000_000),
        )
        # 返回 None 表示没记上，但不抛异常
        assert result is None

    def test_写入文件结构正确(self, isolated_dir):
        cost_store.record_usage("s8", "script_generation",
                                Usage(model_id="qwen-max", input_tokens=1_000_000))
        path = os.path.join(str(isolated_dir), "s8.cost.json")
        assert os.path.exists(path)
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        assert data["session_id"] == "s8"
        assert len(data["records"]) == 1
        rec = data["records"][0]
        assert rec["stage"] == "script_generation"
        assert rec["model_id"] == "qwen-max"
        # 保留原始用量，便于定价变化后重算
        assert rec["usage"]["input_tokens"] == 1_000_000

    def test_清空后归零(self):
        cost_store.record_usage("s9", "script_generation",
                                Usage(model_id="qwen-max", input_tokens=1_000_000))
        assert cost_store.get_summary("s9")["call_count"] == 1
        cost_store.clear("s9")
        assert cost_store.get_summary("s9")["call_count"] == 0
