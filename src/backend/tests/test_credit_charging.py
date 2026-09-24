"""扣费点（预扣 → 结算）的集成测试。

这里不跑真实模型，而是直接驱动 orchestrator 的记账方法，
验证「阶段开始预扣、结束按实际成本结算」这条链路的钱数是对的。

为什么值得单独测
----------------
记账错误的代价和普通 bug 不同：它要么多扣用户的钱，要么少收自己的成本，
而且**不会报错**。所以这里逐分核对金额，而不是只看"有没有报错"。
"""

import os
import sys
import types

import pytest

_BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _BACKEND)

from core.orchestrator import STAGE_LABELS, WorkflowEngine, WorkflowStage  # noqa: E402
from models import cost_store  # noqa: E402
from models import credits_store as cs  # noqa: E402
from models.credits import credits_for  # noqa: E402
from models.credits_store import credits_for_cost  # noqa: E402


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    """成本与账本都写到临时目录。

    账本尤其重要：**真实账本是用户的钱**，测试误写一次就可能凭空发积分。
    """
    monkeypatch.setattr(cs, "CREDITS_DIR", str(tmp_path / "credits"))
    monkeypatch.setattr(cost_store, "SESSIONS_DIR", str(tmp_path / "sessions"))
    yield tmp_path


@pytest.fixture
def engine():
    """不要走 __init__：它会去读真实会话目录，测试不该依赖真实数据。"""
    return WorkflowEngine.__new__(WorkflowEngine)


@pytest.fixture
def state():
    return types.SimpleNamespace(
        session_id="sess1",
        artifacts={
            "storyboard": {
                "episodes": [{"segments": [{"segment_id": "seg_01"}, {"segment_id": "seg_02"}]}]
            }
        },
        meta={"video_model": "doubao-seedance-2-0-260128", "video_resolution": "720P"},
    )


def _record_video_cost(session_id: str, stage: str, tokens: int, model: str):
    """往成本层写一笔真实用量，模拟阶段里跑过一次视频生成。"""
    from models.cost import Usage

    cost_store.record_usage(session_id, stage, Usage(model_id=model, output_tokens=tokens))


class TestReserveOnStageStart:
    def test_视频阶段按镜头数预扣(self, engine, state):
        """2 个镜头 × 70 积分 = 140。"""
        cs.grant(cs.LOCAL_USER, 300, "初始")
        credits = engine._reserve_stage_credits(
            state, WorkflowStage.VIDEO_GENERATION, {}, "sess1:video_generation"
        )
        assert credits == 140
        a = cs.get_account()
        assert a["balance"] == 160
        assert a["locked"] == 140

    def test_预扣原因用中文阶段名(self, engine, state):
        cs.grant(cs.LOCAL_USER, 300, "初始")
        engine._reserve_stage_credits(
            state, WorkflowStage.VIDEO_GENERATION, {}, "sess1:video_generation"
        )
        txn = cs.get_ledger()[0]
        assert txn["reason"] == STAGE_LABELS["video_generation"] == "视频生成"

    def test_文本阶段用实测兜底值(self, engine, state):
        """剧本生成：预跑的实测成本 ¥0.72 → 10 积分。"""
        cs.grant(cs.LOCAL_USER, 300, "初始")
        credits = engine._reserve_stage_credits(
            state, WorkflowStage.SCRIPT_GENERATION, {}, "sess1:script_generation"
        )
        assert credits == credits_for(0.72) == 10

    def test_后期剪辑不预扣(self, engine, state):
        """只调 ffmpeg，没有模型成本，不该占用户余额。"""
        cs.grant(cs.LOCAL_USER, 300, "初始")
        assert engine._reserve_stage_credits(
            state, WorkflowStage.POST_PRODUCTION, {}, "sess1:post_production"
        ) == 0
        assert cs.get_account()["balance"] == 300

    def test_余额不足时中断阶段(self, engine, state):
        """这是预扣的核心价值：在花掉 API 额度**之前**拦住用户。"""
        cs.grant(cs.LOCAL_USER, 50, "不够")
        with pytest.raises(cs.InsufficientCredits) as exc:
            engine._reserve_stage_credits(
                state, WorkflowStage.VIDEO_GENERATION, {}, "sess1:video_generation"
            )
        assert exc.value.shortfall == 90
        assert cs.get_account()["balance"] == 50, "被拦住的预扣不该动余额"

    def test_重复预扣同一ref不重复扣(self, engine, state):
        cs.grant(cs.LOCAL_USER, 300, "初始")
        engine._reserve_stage_credits(state, WorkflowStage.VIDEO_GENERATION, {}, "same")
        engine._reserve_stage_credits(state, WorkflowStage.VIDEO_GENERATION, {}, "same")
        assert cs.get_account()["balance"] == 160, "断点续跑不该二次扣费"

    def test_取不到模型时退回兜底值而不是零(self, engine):
        """估不出单价时也必须扣一笔。

        若返回 0，预扣就形同虚设——用户会在余额不足时走进一个几分钟、
        上百积分的阶段，最后只能产生缺口。
        """
        cs.grant(cs.LOCAL_USER, 300, "初始")
        bare = types.SimpleNamespace(session_id="s", artifacts={}, meta={})
        credits = engine._reserve_stage_credits(
            bare, WorkflowStage.VIDEO_GENERATION, {}, "s:v"
        )
        assert credits > 0

    def test_记账异常不影响生成(self, engine, state, monkeypatch):
        """积分记账不该让生成功能不可用。"""
        def boom(*a, **kw):
            raise RuntimeError("账本坏了")

        monkeypatch.setattr(cs, "reserve", boom)
        assert engine._reserve_stage_credits(
            state, WorkflowStage.SCRIPT_GENERATION, {}, "s:v"
        ) == 0


class TestSettleToActual:
    def test_实际低于预扣要退还差额(self, engine, state):
        """预扣 140（2 个镜头），实际只生成了 1 个 → 只应扣 70。"""
        cs.grant(cs.LOCAL_USER, 300, "初始")
        engine._reserve_stage_credits(
            state, WorkflowStage.VIDEO_GENERATION, {}, "sess1:video_generation"
        )
        _record_video_cost("sess1", "video_generation", 108_000, "doubao-seedance-2-0-260128")

        engine._settle_stage_credits("sess1", "video_generation", "sess1:video_generation")

        a = cs.get_account()
        assert a["balance"] == 230, "应只扣 70，不是 140"
        assert a["total_consumed"] == 70
        assert a["locked"] == 0

    def test_结算金额与实际成本一致(self, engine, state):
        """积分必须由成本层记的**真实金额**换算，不能另算一套。"""
        cs.grant(cs.LOCAL_USER, 300, "初始")
        cs.reserve(cs.LOCAL_USER, 5, "视频", ref="sess1:video_generation",
                   session_id="sess1", stage="video_generation")
        _record_video_cost("sess1", "video_generation", 108_000, "doubao-seedance-2-0-260128")

        engine._settle_stage_credits("sess1", "video_generation", "sess1:video_generation")

        cost = cost_store.get_summary("sess1")["by_stage"]["video_generation"]
        assert cs.get_account()["total_consumed"] == credits_for_cost(cost)

    def test_失败时按实际用量结算而不是全额退回(self, engine, state):
        """阶段中途失败，跑掉的调用是真花了钱的。

        全额退回等于自己承担那部分成本，而且积分与账面成本会对不上。
        """
        cs.grant(cs.LOCAL_USER, 300, "初始")
        engine._reserve_stage_credits(
            state, WorkflowStage.VIDEO_GENERATION, {}, "sess1:video_generation"
        )
        # 失败前已经出了一张图（¥0.20 → 3 积分）
        from models.cost import Usage
        cost_store.record_usage(
            "sess1", "video_generation",
            Usage(model_id="doubao-seedream-4-0-250828", images=1),
        )
        engine._settle_stage_credits("sess1", "video_generation", "sess1:video_generation", "执行失败")

        a = cs.get_account()
        assert a["total_consumed"] == 3, "只应扣实际产生的 3 积分"
        assert a["balance"] == 297

    def test_一分钱没花就等于全额退回(self, engine, state):
        cs.grant(cs.LOCAL_USER, 300, "初始")
        engine._reserve_stage_credits(
            state, WorkflowStage.VIDEO_GENERATION, {}, "sess1:video_generation"
        )
        engine._settle_stage_credits("sess1", "video_generation", "sess1:video_generation", "已取消")
        a = cs.get_account()
        assert a["balance"] == 300
        assert a["total_consumed"] == 0

    def test_结算失败不冒泡(self, engine, monkeypatch):
        """阶段已经跑完，记账失败不该把它变成失败。"""
        def boom(*a, **kw):
            raise RuntimeError("账本写不进去")

        monkeypatch.setattr(cs, "settle", boom)
        engine._settle_stage_credits("sess1", "video_generation", "whatever")  # 不抛

    def test_结算留下可对账的账本(self, engine, state):
        cs.grant(cs.LOCAL_USER, 300, "初始")
        engine._reserve_stage_credits(
            state, WorkflowStage.VIDEO_GENERATION, {}, "sess1:video_generation"
        )
        _record_video_cost("sess1", "video_generation", 108_000, "doubao-seedance-2-0-260128")
        engine._settle_stage_credits("sess1", "video_generation", "sess1:video_generation")
        assert cs.verify(cs.LOCAL_USER)["problems"] == []


class TestFullFilmAccounting:
    def test_十个镜头的成片扣费(self, engine):
        """走一遍多阶段的完整流程，核对总扣费。

        这是最接近"用户真的做完一条片子"的测试。
        """
        # 一条 10 镜头成片要 560+ 积分，注册赠送的 300 **不够**。
        # 这是真实的产品事实，不是测试凑数：300 只够跑一次最小闭环（一条样片）。
        cs.grant(cs.LOCAL_USER, 2000, "买了积分卡")
        st = types.SimpleNamespace(
            session_id="film",
            artifacts={"storyboard": {"episodes": [{"segments": [
                {"segment_id": f"seg_{i:02d}"} for i in range(1, 11)
            ]}]}},
            meta={"video_model": "doubao-seedance-2-0-fast-260128",
                  "video_resolution": "720P"},
        )

        # 前期三个阶段（文本/图片）
        for stage, key in [
            (WorkflowStage.SCRIPT_GENERATION, "script_generation"),
            (WorkflowStage.STORYBOARD, "storyboard"),
        ]:
            ref = f"film:{key}"
            reserved = engine._reserve_stage_credits(st, stage, {}, ref)
            # 模拟实际比预扣便宜一点（真实预跑里很常见）
            from models.cost import Usage
            cost_store.record_usage("film", key, Usage(model_id="qwen-max",
                                                       input_tokens=100_000, output_tokens=50_000))
            engine._settle_stage_credits("film", key, ref)
            assert reserved > 0

        # 视频阶段：10 个镜头 × Fast 档 56 积分
        ref = "film:video_generation"
        reserved = engine._reserve_stage_credits(st, WorkflowStage.VIDEO_GENERATION, {}, ref)
        assert reserved == 560, f"10 镜头 × 56 = 560，实际 {reserved}"
        for _ in range(10):
            _record_video_cost("film", "video_generation", 108_000,
                               "doubao-seedance-2-0-fast-260128")
        engine._settle_stage_credits("film", "video_generation", ref)

        a = cs.get_account()
        assert a["locked"] == 0, "不应留下悬挂预扣"
        assert cs.verify(cs.LOCAL_USER)["problems"] == []

        # 逐阶段核对。注意**不是**对总成本一次换算——每阶段各结算一次、
        # 各自取整，与"先汇总再取整"可能差 1 积分，这是预期行为。
        video_cost = cost_store.get_summary("film")["by_stage"]["video_generation"]
        assert video_cost == pytest.approx(39.96, abs=0.01)   # 10 个片段 × ¥3.996
        assert credits_for_cost(video_cost) == 559            # round(39.96 × 14)

        text_cost = 0.1 * 2.4 + 0.05 * 9.6                    # qwen-max 10 万入 / 5 万出
        assert credits_for_cost(text_cost) == 10              # 剧本与分镜各 10

        assert a["total_consumed"] == 559 + 10 + 10


class TestFreeQuotaReality:
    """注册赠送 300 积分到底能做什么——把产品事实锁进测试。

    300 积分＝一次最小闭环（创意 → 看到一条 5 秒样片），
    **不够**做一条 10 镜头成片。这不是缺陷，是定价设计的必然结果，
    但很容易在演示时被问到，所以写成断言。
    """

    def test_三百积分够跑最小闭环(self, engine):
        """最小闭环：剧本 10 + 分镜 13 + 角色图×2 6 + 参考图×2 6 + 样片 70 = 105。"""
        cs.grant_signup_bonus(cs.LOCAL_USER)
        minimal = credits_for(0.72) + credits_for(0.94) + 3 * 2 + 3 * 2 + credits_for(4.97)
        assert minimal == 105
        assert cs.get_account()["balance"] >= minimal

    def test_三百积分不够做十镜头成片(self, engine):
        cs.grant_signup_bonus(cs.LOCAL_USER)
        st = types.SimpleNamespace(
            session_id="film2",
            artifacts={"storyboard": {"episodes": [{"segments": [
                {"segment_id": f"seg_{i:02d}"} for i in range(1, 11)
            ]}]}},
            meta={"video_model": "doubao-seedance-2-0-fast-260128",
                  "video_resolution": "720P"},
        )
        with pytest.raises(cs.InsufficientCredits) as exc:
            engine._reserve_stage_credits(st, WorkflowStage.VIDEO_GENERATION, {}, "film2:v")
        # 缺 260：560 需要 vs 300 可用
        assert exc.value.shortfall == 260
