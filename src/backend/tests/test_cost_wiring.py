"""成本记账链路的测试。

这一组守的是本项目最严重的一次事故
----------------------------------
`record_usage()` 写好后**整整一轮开发没被任何生产代码调用过**：
模块齐全、测试全绿、接口都返回 200，但真实项目一条成本都没记下
（`code/data/sessions/*.cost.json` 一个都没有）。

两个根因，这里各有一组测试盯着：

1. **客户端把用量丢了**（`response.usage` / `data["usage"]` 被 `return content` 顺手扔掉）
   → `TestClientReportsUsage`
2. **计费上下文没有传进线程池**（模型调用有 6 处在工作线程里，
   而 ThreadPoolExecutor 不会自动复制 contextvars）
   → `TestContextPropagation`

第 2 条尤其阴险：漏了不报错、不写警告，只是账少了。
所以除了行为测试，最后还加了一条**静态检查**，禁止裸用 `executor.submit`。
"""

import os
import sys
from concurrent.futures import ThreadPoolExecutor

import pytest

_BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _BACKEND)

from models import cost_store  # noqa: E402
from models.cost import Usage  # noqa: E402
from models.cost_store import (  # noqa: E402
    cost_scope,
    current_scope,
    report_usage,
    submit_with_cost_context,
)


@pytest.fixture(autouse=True)
def isolated_dir(tmp_path, monkeypatch):
    """成本写到临时目录，不污染真实会话。"""
    monkeypatch.setattr(cost_store, "SESSIONS_DIR", str(tmp_path))
    yield tmp_path


class TestCostScope:
    def test_作用域内记账落到正确会话与阶段(self):
        with cost_scope("s1", "script_generation"):
            report_usage(Usage(model_id="qwen-max", input_tokens=1_000_000))
        s = cost_store.get_summary("s1")
        assert s["call_count"] == 1
        assert s["total"] == pytest.approx(2.4)
        assert s["by_stage"]["script_generation"] == pytest.approx(2.4)

    def test_作用域外静默跳过不报错(self):
        """沙盒里的独立调用不属于任何会话，不该记账也不该炸。"""
        assert report_usage(Usage(model_id="qwen-max", input_tokens=1_000_000)) is None
        assert cost_store.get_summary("没记过的会话")["call_count"] == 0

    def test_作用域结束后不再记账(self):
        with cost_scope("s2", "video_generation"):
            report_usage(Usage(model_id="wan2.7-i2v", seconds=5))
        assert current_scope() is None
        report_usage(Usage(model_id="wan2.7-i2v", seconds=5))
        assert cost_store.get_summary("s2")["call_count"] == 1, "作用域逃逸了"

    def test_阶段可显式覆盖(self):
        with cost_scope("s3", "video_generation"):
            report_usage(Usage(model_id="wan2.7-i2v", seconds=5), stage="reference_generation")
        s = cost_store.get_summary("s3")
        assert s["by_stage"] == {"reference_generation": pytest.approx(3.0)}

    def test_嵌套作用域结束后回到外层(self):
        with cost_scope("outer", "script_generation"):
            with cost_scope("inner", "storyboard"):
                report_usage(Usage(model_id="qwen-max", input_tokens=1_000_000))
            report_usage(Usage(model_id="qwen-max", input_tokens=1_000_000))
        assert cost_store.get_summary("inner")["call_count"] == 1
        assert cost_store.get_summary("outer")["call_count"] == 1

    def test_异常也会退出作用域(self):
        with pytest.raises(RuntimeError):
            with cost_scope("s4", "script_generation"):
                raise RuntimeError("阶段失败")
        assert current_scope() is None, "异常路径泄漏了计费上下文"


class TestContextPropagation:
    """线程池不会自动复制 contextvars —— 这一组证明我们处理了它。"""

    def test_helper把作用域带进工作线程(self):
        with cost_scope("pool1", "reference_generation"):
            with ThreadPoolExecutor(max_workers=2) as ex:
                futures = [
                    submit_with_cost_context(
                        ex, lambda: report_usage(Usage(model_id="qwen-max", input_tokens=1_000_000))
                    )
                    for _ in range(3)
                ]
                for f in futures:
                    f.result()
        assert cost_store.get_summary("pool1")["call_count"] == 3

    def test_裸submit会丢账_这正是要防的坑(self):
        """反证：不用 helper 就真的丢。这条测试是那份恐惧的存档。

        如果哪天有人觉得 helper 多余，这条测试会告诉他为什么不多余。
        """
        def worker():
            return report_usage(Usage(model_id="qwen-max", input_tokens=1_000_000))

        with cost_scope("pool2", "reference_generation"):
            with ThreadPoolExecutor(max_workers=1) as ex:
                assert ex.submit(worker).result() is None   # 工作线程里看不到作用域
        assert cost_store.get_summary("pool2")["call_count"] == 0

    def test_没有作用域时helper也不报错(self):
        """沙盒等无会话场景：helper 仍可用，只是不记账。"""
        with ThreadPoolExecutor(max_workers=1) as ex:
            fut = submit_with_cost_context(ex, lambda: "ok")
            assert fut.result() == "ok"


class TestClientReportsUsage:
    """客户端必须把用量交给成本层，而不是丢掉。"""

    def test_dashscope用量提取(self):
        from models.usage_report import report_chat_usage

        class Resp:
            usage = {"input_tokens": 1000, "output_tokens": 500}

        with cost_scope("c1", "script_generation"):
            total = report_chat_usage("qwen-max", Resp())
        assert total == 1500
        # 1000/1e6×2.4 + 500/1e6×9.6 = 0.0024 + 0.0048
        assert cost_store.get_summary("c1")["total"] == pytest.approx(0.0072, abs=1e-6)

    def test_兼容prompt_completion字段名(self):
        from models.usage_report import report_chat_usage

        class Resp:
            usage = {"prompt_tokens": 1000, "completion_tokens": 0}

        with cost_scope("c2", "script_generation"):
            assert report_chat_usage("qwen-max", Resp()) == 1000

    def test_没有用量时不写假记录(self):
        from models.usage_report import report_chat_usage

        class Resp:
            usage = None

        with cost_scope("c3", "script_generation"):
            assert report_chat_usage("qwen-max", Resp()) is None
        assert cost_store.get_summary("c3")["call_count"] == 0

    def test_图片按张记账(self):
        """图片是**按张**计费，不是按次。"""
        with cost_scope("c4", "reference_generation"):
            report_usage(Usage(model_id="doubao-seedream-4-0-250828", images=4))
        s = cost_store.get_summary("c4")
        assert s["total"] == pytest.approx(0.80)
        assert s["records"][0]["breakdown"] == "4 张 × 0.2 元/张"

    def test_视频按秒记账且区分分辨率音轨(self):
        with cost_scope("c5", "video_generation"):
            report_usage(Usage(model_id="wan2.6-i2v-flash", seconds=5,
                               resolution="720P", audio=False))
            report_usage(Usage(model_id="wan2.6-i2v-flash", seconds=5,
                               resolution="1080P", audio=True))
        s = cost_store.get_summary("c5")
        # 0.75 + 2.50
        assert s["total"] == pytest.approx(3.25)
        labels = [r["breakdown"] for r in s["records"]]
        assert any("720P 无声" in x for x in labels)
        assert any("1080P 带音" in x for x in labels)

    def test_seedance按输出tokens记账(self):
        """回归：Seedance 的 tokens 是**输出视频 tokens**。

        注册表里的费率必须落在 `output_per_million`。若落在 `input_per_million`，
        客户端报的 output_tokens 会按 0 元计费——金额算成 0，而且不报错。
        """
        with cost_scope("c6", "video_generation"):
            report_usage(Usage(model_id="doubao-seedance-2-0-fast-260128", output_tokens=108_900))
        s = cost_store.get_summary("c6")
        assert s["total"] > 4.0, "Seedance 输出 tokens 被按 0 元计费了"


class TestNoBareSubmitInProduction:
    """静态检查：生产代码里不允许出现裸 `executor.submit`。

    漏用 helper 不会报错，只会让账变少——靠行为测试很难覆盖到
    "以后新加的那个线程池"。所以这里直接扫源码。
    """

    def test_没有裸executor_submit(self):
        offenders = []
        for root, dirs, files in os.walk(_BACKEND):
            dirs[:] = [d for d in dirs if d not in {".venv", "__pycache__", "tests"}]
            for name in files:
                if not name.endswith(".py"):
                    continue
                path = os.path.join(root, name)
                with open(path, encoding="utf-8") as fh:
                    for lineno, line in enumerate(fh, 1):
                        if "executor.submit(" not in line:
                            continue
                        # 放行 helper 自己的实现（它必须直接调 submit）。
                        # 用"必须是 ctx.run"来放行，而不是整文件跳过——
                        # 否则以后在 cost_store.py 里新加一处裸 submit 就漏检了。
                        if "executor.submit(ctx.run" in line:
                            continue
                        offenders.append(f"{os.path.relpath(path, _BACKEND)}:{lineno}")
        assert not offenders, (
            "以下位置直接用了 executor.submit，会让线程池里的模型调用丢账。\n"
            "请改用 cost_store.submit_with_cost_context(executor, fn, ...)：\n  "
            + "\n  ".join(offenders)
        )

    def test_客户端都报了用量(self):
        """这 6 个客户端负责把用量交给成本层，改坏了就会静默丢账。"""
        expected = {
            "models/llm_dashscope.py": "report_chat_usage",
            "models/vlm_dashscope.py": "report_chat_usage",
            "models/llm_deepseek.py": "report_chat_usage",
            "models/video_seedance.py": "report_usage",
            "models/video_dashscope.py": "report_usage",
            "models/image_client.py": "report_usage",
        }
        for rel, marker in expected.items():
            src = open(os.path.join(_BACKEND, rel), encoding="utf-8").read()
            assert marker in src, f"{rel} 没有上报用量（应有 {marker}）"

    def test_主用LLM已登记定价(self):
        """主用 LLM 换了模型，必须同时登记定价——否则文本成本会重新变成 0。

        这是"换模型"最容易漏的一步：模型能跑通、回复也对，
        但账本里什么都记不下（`compute_cost` 找不到定价就跳过）。
        """
        import yaml

        from models.pricing import PRICING

        cfg = yaml.safe_load(open(os.path.join(_BACKEND, "config.yaml"), encoding="utf-8"))
        llm_model = cfg["models"]["llm"]
        assert llm_model in PRICING, (
            f"config 里主用 LLM 是 {llm_model}，但 pricing 注册表里没有它——"
            "文本成本会被静默跳过"
        )

    def test_DeepSeek推理模型的用量能记账(self):
        """DeepSeek V4.1 Flash 是推理模型：输出 tokens 里含 reasoning。

        reasoning 已包含在 completion_tokens 中，应按 completion_tokens 计费，
        不要因为看到 reasoning_tokens 就再加一遍。
        """
        from models.usage_report import report_chat_usage

        class Resp:
            choices = []
            usage = {
                "prompt_tokens": 52,
                "completion_tokens": 293,
                "completion_tokens_details": {"reasoning_tokens": 200},
            }

        with cost_scope("llm1", "script_generation"):
            total = report_chat_usage("deepseek-v4-1-flash-260910", Resp())
        assert total == 345, "总量应为输入+输出，reasoning 已含在输出里"

        s = cost_store.get_summary("llm1")
        # 52/1e6×1.0 + 293/1e6×4.0
        assert s["total"] == pytest.approx(0.001224, abs=1e-6)

    def test_内容为空也要记账(self):
        """回归：推理模型把 max_tokens 花光时 content 为空并触发重试。

        那次调用**已经计费了**，所以必须在确认内容可用之前就记账，
        否则重试的钱全部漏记（这也是 P2-1 那个缺口的具体表现）。
        """
        from models.usage_report import report_chat_usage

        class Resp:
            choices = []          # 内容为空
            usage = {"prompt_tokens": 100, "completion_tokens": 20000}

        with cost_scope("llm2", "script_generation"):
            total = report_chat_usage("deepseek-v4-1-flash-260910", Resp())
        assert total == 20100
        assert cost_store.get_summary("llm2")["call_count"] == 1


class TestVerifyScriptIsReadOnlyInDryRun:
    """`verify_cost_wiring.py --dry-run` 必须**不动任何已有记录**。

    这里踩过一次真实事故：`cost_store.clear()` 原先写在 dry-run 判断之前，
    结果"只是看看计划"的那次运行把上一次真跑花 ¥1.87 留下的证据删了。
    只读模式必须是只读的——与"确认前不删数据"是同一条原则。
    """

    def test_dry_run不会清掉已有记录(self, isolated_dir):
        import subprocess

        cost_store.record_usage("verify_cost_wiring", "video_generation",
                                Usage(model_id="doubao-seedance-2-0-fast-260128",
                                      output_tokens=50_638))
        before = cost_store.get_summary("verify_cost_wiring")
        assert before["call_count"] == 1

        env = dict(os.environ)
        # 让子进程也写到这个临时目录，而不是真实会话目录
        env["LILOVIDEO_SESSIONS_DIR"] = str(isolated_dir)
        proc = subprocess.run(
            [sys.executable, "verify_cost_wiring.py", "--dry-run"],
            cwd=_BACKEND, env=env, capture_output=True, text=True, timeout=120,
        )
        assert proc.returncode == 0, proc.stderr[-800:]

        after = cost_store.get_summary("verify_cost_wiring")
        assert after["call_count"] == 1, "dry-run 把已有记录删了"
        assert after["total"] == pytest.approx(before["total"])
