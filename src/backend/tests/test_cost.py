"""成本计算单元测试。

重点验证三件事：
1. 已核实定价的模型能算出正确金额
2. 未登记定价的模型返回 None，而不是 0（"未知"与"免费"必须可区分）
3. 缓存命中的输入不被重复计价
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from models.cost import Usage, compute_cost, estimate_video_cost, token_rate  # noqa: E402
from models.pricing import (  # noqa: E402
    PRICING,
    SEEDANCE_RESOLUTION_PIXELS,
    SEEDANCE_TOKENS_PER_SECOND_720P,
    get_price,
    seedance_tokens,
    unverified_models,
)


class TestPricingRegistry:
    def test_已核实的模型都带来源(self):
        for spec in PRICING.values():
            if spec.verified:
                assert spec.source, f"{spec.model_id} 标记为已核实但没有来源"
                assert spec.note, f"{spec.model_id} 标记为已核实但没有核实说明"

    def test_未登记的模型返回None(self):
        assert get_price("这个模型不存在") is None
        assert get_price("") is None

    def test_未核实清单可查询(self):
        # 至少能列出未核实项，供界面提示
        assert isinstance(unverified_models(), list)


class TestPerTokenCost:
    def test_qwen_max_精确计算(self):
        """qwen-max：输入 2.4、输出 9.6 元/百万 tokens。"""
        # 100 万输入 + 100 万输出 = 2.4 + 9.6 = 12.0
        r = compute_cost(Usage(model_id="qwen-max", input_tokens=1_000_000, output_tokens=1_000_000))
        assert r is not None
        assert r.amount == pytest.approx(12.0)
        assert r.currency == "CNY"
        assert r.verified is True

    def test_qwen37plus_精确计算(self):
        """qwen3.7-plus：输入 2.0、输出 8.0 元/百万 tokens。"""
        r = compute_cost(Usage(model_id="qwen3.7-plus", input_tokens=500_000, output_tokens=250_000))
        assert r is not None
        # 0.5 * 2.0 + 0.25 * 8.0 = 1.0 + 2.0 = 3.0
        assert r.amount == pytest.approx(3.0)

    def test_零用量返回None而不是零(self):
        """关键：没有用量时不能返回 0，那会被误解为免费。"""
        assert compute_cost(Usage(model_id="qwen-max")) is None
        assert compute_cost(Usage(model_id="qwen-max", input_tokens=0, output_tokens=0)) is None

    def test_未登记模型返回None而不是零(self):
        r = compute_cost(Usage(model_id="未知模型", input_tokens=1_000_000, output_tokens=1_000_000))
        assert r is None

    def test_缓存命中不重复计价(self):
        """缓存命中的 tokens 从普通输入中扣除，按更便宜的缓存价计价。"""
        # 全部命中缓存：100 万 tokens × 0.48 = 0.48
        r = compute_cost(Usage(
            model_id="qwen-max",
            input_tokens=1_000_000,
            cached_input_tokens=1_000_000,
            output_tokens=0,
        ))
        assert r is not None
        assert r.amount == pytest.approx(0.48)

    def test_部分命中缓存(self):
        # 输入 100 万，其中 40 万命中缓存
        # 普通输入 60 万 × 2.4 = 1.44；缓存 40 万 × 0.48 = 0.192
        r = compute_cost(Usage(
            model_id="qwen-max",
            input_tokens=1_000_000,
            cached_input_tokens=400_000,
        ))
        assert r is not None
        assert r.amount == pytest.approx(1.44 + 0.192)

    def test_缓存数超过输入数时不产生负价格(self):
        """防御：缓存命中数不应大于输入总数，异常数据不能算出负数。"""
        r = compute_cost(Usage(
            model_id="qwen-max",
            input_tokens=100_000,
            cached_input_tokens=500_000,
        ))
        assert r is not None
        assert r.amount >= 0
        # 缓存被夹到 10 万，全部按缓存价：0.1 × 0.48 = 0.048
        assert r.amount == pytest.approx(0.048)

    def test_未登记缓存价时按输入价计费而不是免费(self):
        """回归：缓存 tokens 曾经在"没登记缓存价"时被算成 **0 元**。

        旧代码是 `if cached and cache_rate is not None:` —— 只要
        `cached_input_per_million` 是 None，这部分 tokens 就一分钱不算，
        而且不报错、不留痕。30 万缓存 tokens 会凭空消失成 ¥0。

        缓存命中的正确定价只会**更便宜**，不可能免费，所以退到输入价是安全方向。
        方舟控制台的 DeepSeek 价目页恰好只给了输入/输出两项、没有缓存价，
        这条路径是真实会走到的。
        """
        from models.pricing import PRICING, PriceSpec

        spec = PriceSpec(
            model_id="test-no-cache-rate",
            provider="ark",
            billing="per_token",
            input_per_million=1.0,
            output_per_million=4.0,
            cached_input_per_million=None,   # 没登记缓存价
            verified=True,
            source="（测试夹具）",
            note="测试夹具",
        )
        try:
            PRICING[spec.model_id] = spec
            r = compute_cost(Usage(
                model_id=spec.model_id,
                input_tokens=1_000_000,
                cached_input_tokens=300_000,
            ))
        finally:
            PRICING.pop(spec.model_id, None)

        assert r is not None
        # 70 万按输入价 1.0 + 30 万缓存也按 1.0 = 1.0 元（而不是 0.7 元）
        assert r.amount == pytest.approx(1.0), "缓存 tokens 被算成免费了"
        assert "未登记缓存价" in r.breakdown

    def test_主用LLM价格已核实(self):
        """方舟控制台价目页确认：推理输入 1、推理输出 4 元/百万 tokens。"""
        from models.pricing import PRICING

        spec = PRICING["deepseek-v4-1-flash-260910"]
        assert spec.verified is True
        assert spec.input_per_million == 1.0
        assert spec.output_per_million == 4.0
        # 控制台页没有缓存价，所以不能登记一个没核到的数
        assert spec.cached_input_per_million is None


class TestVideoCost:
    def test_seedance_按tokens计费(self):
        """Seedance 2.0 官方为 per-token（46 元/百万）。"""
        # 官方实测：15 秒视频消耗 30.888 万 tokens
        r = compute_cost(Usage(model_id="doubao-seedance-2-0-260128", output_tokens=308_880))
        assert r is not None
        # 0.30888 × 46 ≈ 14.21
        assert r.amount == pytest.approx(14.21, abs=0.01)

    def test_seedance_预估按秒(self):
        """生成前预估：按实测 tokens/秒 折算。

        旧实现把 Seedance 折算率**硬编码成 1.00 元/秒**（取自媒体口径）。
        现在改为从费率与实测 tokens/秒 推导：46 元/百万 × 21780 tokens/秒
        = ¥1.0019/秒，因此 10 秒是 ¥10.02 而不是 ¥10.00。
        差别虽小，但 fast 档（¥0.81）和 mini 档（¥0.50）原来也被当成 ¥1.00，
        那是 25%~100% 的报价错误。
        """
        r = estimate_video_cost("doubao-seedance-2-0-260128", 10)
        assert r is not None
        # 官方公式：1280×720×24×10 ÷ 1024 = 216,000 tokens × 46 元/百万 ≈ ¥9.94。
        # 早先写过 ¥10.02 / ¥9.98，都是基于"实测反推 + 倍数外推"的错法，
        # 官方价目页出来后才定为准。
        assert r.amount == pytest.approx(9.94, abs=0.01)
        # 关键：这是换算估计，必须标记为未核实，不能冒充账单
        assert r.verified is False
        assert "实测" in r.breakdown or "tokens" in r.breakdown

    def test_seedance各档成本互不相同(self):
        """核心回归：同一系列的每一档必须算出**不同**的成本。

        这正是旧实现的 bug——靠 `model_id.startswith("doubao-seedance-2-0")`
        判断，把 mini / fast / 标准全按 1 元/秒报了。

        按 5 秒比较（公式在这个时长上有实测背书）。
        """
        expected = {
            "doubao-seedance-2-0-260128": 4.97,       # 46 元/百万
            "doubao-seedance-2-0-fast-260128": 4.00,  # 37 元/百万
            "doubao-seedance-2-0-mini-260615": 2.48,  # 23 元/百万
            "doubao-seedance-2-5-260628": 7.56,       # 70 元/百万（定价待复核）
        }
        seen = {}
        for model_id, cost in expected.items():
            r = estimate_video_cost(model_id, 5)
            assert r is not None, f"{model_id} 应能预估"
            assert r.amount == pytest.approx(cost, abs=0.01), f"{model_id} 折算不对"
            seen[model_id] = r.amount
        assert len(set(seen.values())) == len(seen), "各档成本不应相同"

    def test_mini档折算与官方口径吻合(self):
        """独立校验：官方称 mini 720P 单秒约 0.5 元、较标准版降低约一半。

        按 5 秒算再折算每秒：¥2.50 / 5 = ¥0.50，与官方口径逐字吻合。
        """
        r = estimate_video_cost("doubao-seedance-2-0-mini-260615", 5)
        assert r is not None
        assert r.amount / 5 == pytest.approx(0.50, abs=0.01)

    def test_报价与官方价目页逐行对齐(self):
        """Seedance 2.5 的三档报价必须与方舟控制台价目页一致。

        官方页（5 秒 / 16:9 / 不含视频输入）：480P ¥3.36、720P ¥7.56、1080P ¥18.71。
        注意 1080P 的**费率本身更高**（77 vs 70），若只存一个费率会少收 9%。
        """
        for res, expected in [("480P", 3.36), ("720P", 7.56), ("1080P", 18.71)]:
            r = estimate_video_cost("doubao-seedance-2-5-260628", 5, resolution=res)
            assert r is not None, f"{res} 应能报价"
            assert r.amount == pytest.approx(expected, abs=0.01), f"{res} 与官方页不符"

    def test_1080P费率不套用720P(self):
        """回归：1080P 必须用 77 而不是 70。"""
        r = estimate_video_cost("doubao-seedance-2-5-260628", 5, resolution="1080P")
        assert "77 元/百万" in r.breakdown

    def test_2_0系未取到480P与1080P费率所以不报价(self):
        """2.0 系只取到 720P 费率；缺的档位宁可报"未知"，也不拿 720P 的费率去充。"""
        assert estimate_video_cost("doubao-seedance-2-0-260128", 5, resolution="480P") is None
        assert estimate_video_cost("doubao-seedance-2-0-260128", 5, resolution="1080P") is None
        assert estimate_video_cost("doubao-seedance-2-0-260128", 5, resolution="720P") is not None


    def test_通义按秒确定报价(self):
        """通义系 per_second：成本完全确定，verified 跟随定价本身。"""
        r = estimate_video_cost("wan2.7-i2v", 5)
        assert r is not None
        assert r.amount == pytest.approx(3.0)
        assert r.verified is True
        assert "720P" in r.breakdown

    def test_通义带音档按档位报价(self):
        """同一模型的不同档位必须报不同的价，且档位名出现在说明里。"""
        silent = estimate_video_cost("wan2.6-i2v-flash", 5, variant="720P 无声")
        audio = estimate_video_cost("wan2.6-i2v-flash", 5, variant="720P 带音")
        assert silent is not None and audio is not None
        assert silent.amount == pytest.approx(0.75)
        assert audio.amount == pytest.approx(1.50)
        assert "带音" in audio.breakdown

    def test_未登记的档位报未知而不是退回默认档(self):
        """防御：用户选了不存在的档位时，不能悄悄按默认档报价。"""
        assert estimate_video_cost("wan2.6-i2v-flash", 5, variant="4K 带音") is None

    def test_未登记的分辨率报未知(self):
        assert estimate_video_cost("wan2.7-i2v", 5, resolution="4K") is None

    def test_未知模型的预估返回None(self):
        assert estimate_video_cost("不存在的视频模型", 10) is None


class TestSeedanceTokenFormula:
    """官方公式：tokens = 宽 × 高 × 帧率 × 计费时长 ÷ 1024，帧率 24。

    分辨率由方舟控制台价目页的 **6 行示例**反推确认（3 档 × 2 种时长），
    全部精确吻合。这是报价的地基，必须锁死。

    **曾经在这里犯过错**：在拿到官方价目页之前，本文件按单次实测反推出
    "480P 的有效像素是 864×496"，还写了单测锁死。官方价目页出来后证明是错的——
    480P 就是 854×480。一个样本可以精确命中多种解释，精确不等于正确。
    """

    # 官方价目页的 6 行，逐行复现
    OFFICIAL = [
        ("480P", 5, 48_037.5),
        ("720P", 5, 108_000.0),
        ("1080P", 5, 243_000.0),
        ("480P", 20, 192_150.0),
        ("720P", 20, 432_000.0),
        ("1080P", 20, 972_000.0),
    ]

    def test_复现官方价目页六行(self):
        for res, secs, expected in self.OFFICIAL:
            got = seedance_tokens(secs, res)
            assert got == pytest.approx(expected, abs=0.51), f"{res} {secs}s 与官方不符"

    def test_分辨率取官方值(self):
        assert SEEDANCE_RESOLUTION_PIXELS == {
            "480P": (854, 480), "720P": (1280, 720), "1080P": (1920, 1080)
        }

    def test_与每秒常量一致(self):
        assert seedance_tokens(1, "720P") == pytest.approx(SEEDANCE_TOKENS_PER_SECOND_720P)

    def test_含视频输入按输入加输出总时长计费(self):
        """这是"含视频输入"单价更低却常常更贵的原因。"""
        assert seedance_tokens(10, "720P", input_seconds=10) == pytest.approx(432_000.0)
        # 是普通 5 秒生成的 4 倍用量
        assert seedance_tokens(10, "720P", input_seconds=10) == pytest.approx(
            seedance_tokens(5, "720P") * 4
        )

    def test_实测偏差记录在案(self):
        """实测偏高于官方公式，方向与量级都记下来，免得日后被当成 bug。

        720P：实测 108,900 vs 官方 108,000（+0.83%，报价取整后无影响）
        480P：实测  50,638 vs 官方  48,037.5（+5.41%，故 480P 上架前需重测）
        """
        official_720 = seedance_tokens(5, "720P")
        assert 108_900 > official_720
        assert (108_900 - official_720) / official_720 < 0.01

        official_480 = seedance_tokens(5, "480P")
        assert 50_638 > official_480
        assert 0.03 < (50_638 - official_480) / official_480 < 0.07

    def test_未登记分辨率返回None而不是猜(self):
        assert seedance_tokens(5, "4K") is None
        assert seedance_tokens(0, "720P") is None


class TestPricingInvariants:
    """注册表自身的结构约束。放这里是因为违反约束会静默算错钱。"""

    def test_默认档必须存在于variants里(self):
        for spec in PRICING.values():
            if spec.variants and spec.per_second is not None:
                values = [price for _, price in spec.variants]
                assert spec.per_second in values, (
                    f"{spec.model_id} 的 per_second={spec.per_second} 不在 variants 里，"
                    "默认档与档位表脱节了"
                )

    def test_档位名不重复(self):
        for spec in PRICING.values():
            names = [name for name, _ in spec.variants]
            assert len(names) == len(set(names)), f"{spec.model_id} 档位名重复"

    def test_视频模型要么按秒要么有实测tokens每秒(self):
        """per_token 的视频模型必须带实测 tokens/秒，否则生成前无法报价。"""
        for spec in PRICING.values():
            if spec.billing != "per_token":
                continue
            if "seedance" not in spec.model_id:
                continue  # LLM 不适用
            assert spec.tokens_per_second_720p, f"{spec.model_id} 缺少实测 tokens/秒"
            # 带分辨率取费率（费率分档，不带分辨率取不出来是正常的）
            assert token_rate(spec, "720P"), f"{spec.model_id} 缺少 720P 费率"


class TestUnverifiedHandling:
    def test_未核实定价仍能计算但带标记(self, unverified_video_spec):
        """未核实模型可以算，但必须带 verified=False，让上层能提示用户。

        夹具的来源见 `tests/conftest.py`：这里**注入**一条假规格，
        而不是借用注册表里的真实模型——真实模型的核实状态会变，
        用它当夹具会让测试莫名其妙地红。
        """
        r = compute_cost(Usage(model_id=unverified_video_spec.model_id, input_tokens=1_000_000))
        assert r is not None
        assert r.verified is False
