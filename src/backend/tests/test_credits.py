"""积分换算的单元测试。

这一组测试里最重要的是 `TestMarkupAlgebra`：它锁住实付倍数是 **2.5K²** 而不是 2.5K。

为什么值得单独立一组
--------------------
这个常数曾经算错，而且错了很久没被发现，因为**所有用同一个错公式算出来的数
都互相自洽**——设计毛利、实付倍数、K 对比表，一路错到底但彼此一致，
靠内部一致性查不出来。它甚至导致了一条错误的产品建议
（"毛利比行业低 8 个点，应该涨价"，见《竞品定价调研.md》）。

唯一能证伪它的，是拿"由具体例子直接算出的数"去对账。
所以这里的测试也采用同一个方法：**不重新推导公式，而是走一遍真实例子**，
看算出来的钱与文档里独立记录的实例毛利是否吻合。
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from models.credits import (  # noqa: E402
    CREDITS_PER_YUAN_COST,
    DEFAULT_K,
    YUAN_PER_CREDIT_UNIT,
    credits_for,
    discount_floor,
    margin,
    markup,
    revenue_for,
    yuan_per_credit,
)


class TestMarkupAlgebra:
    """实付倍数 = 10 × K × (K × 0.25) = 2.5K²。K 出现两次。"""

    def test_倍数是2_5K平方而不是2_5K(self):
        k = 1.4
        assert markup(k) == pytest.approx(2.5 * k * k)
        assert markup(k) == pytest.approx(4.90)
        # 明确否掉那个曾经用过的错值
        assert markup(k) != pytest.approx(2.5 * k)

    def test_毛利与倍数的关系(self):
        for k in (1.0, 1.2, 1.4, 1.8, 2.5):
            assert margin(k) == pytest.approx(1 - 1 / markup(k))

    def test_K等于1时毛利恰好60个点(self):
        """K=1 时实付 2.5 倍，毛利 60%——这个锚点两种算法一致，不能变。"""
        assert markup(1.0) == pytest.approx(2.50)
        assert margin(1.0) == pytest.approx(0.60)

    def test_折扣下限与毛利互补(self):
        for k in (1.0, 1.4, 2.0):
            assert discount_floor(k) == pytest.approx(1 - margin(k))

    def test_折扣下限在K14时是20_4个百分点(self):
        """这个数被两次误判过，但**一直是对的**，锁住它。"""
        assert discount_floor(1.4) == pytest.approx(0.204, abs=0.001)


class TestCrossCheckWithWorkedExample:
    """拿文档里那个走完整流程的实例来对账——这是唯一能证伪公式的办法。"""

    def test_十秒成片的实例毛利(self):
        """《积分与会员模型.md》§4：成本 ¥18.29、257 积分、实付 ¥89.95、实例毛利 79.7%。

        注意这里的成本与积分都是**独立**给出的（成本来自实测用量、积分来自逐项取整），
        所以这个对账是有效的，不是同义反复。
        """
        cost, credits = 18.29, 257
        revenue = revenue_for(credits, DEFAULT_K)
        assert revenue == pytest.approx(89.95, abs=0.01)
        actual_margin = (revenue - cost) / revenue
        assert actual_margin == pytest.approx(0.797, abs=0.001)
        # 设计毛利与实例毛利只应差取整的量级（<0.5 个点），
        # 若差到 8 个点就说明公式又错了
        assert abs(actual_margin - margin(DEFAULT_K)) < 0.005

    def test_打五折后的毛利(self):
        """《组合计价.md》§3.3：特价档限时 5 折，实际毛利 59%。

        这个数只与 4.90 倍自洽；按 3.5 倍算会得到 42.9%。用它当第二个独立见证。
        """
        k = DEFAULT_K
        revenue_at_half = revenue_for(100, k) * 0.5
        cost = 100 * yuan_per_credit(k) / markup(k)   # 反推这 100 积分的成本
        assert (revenue_at_half - cost) / revenue_at_half == pytest.approx(0.592, abs=0.005)


class TestCreditsFor:
    def test_已公布五档数值不变(self):
        published = [(0.75, 10), (1.50, 21), (3.00, 42), (4.03, 56), (5.01, 70)]
        for cost, expected in published:
            assert credits_for(cost, DEFAULT_K) == expected

    def test_点半时取到偶数而不是随浮点漂移(self):
        """25 积分档：成本 ¥2.25 恰好落在 31.5。

        改 Decimal 之前这里会因为浮点误差算成 31（而 ¥0.75 的 10.5 算成 10），
        同样都是 .5 却分两派。现在统一四舍六入五成双。
        """
        assert credits_for(2.25, DEFAULT_K) == 32   # 31.5 → 32（偶）
        assert credits_for(0.75, DEFAULT_K) == 10   # 10.5 → 10（偶）

    def test_单调不减(self):
        """成本越高积分不得越低。"""
        prev = -1
        cost = 0.0
        while cost < 10:
            c = credits_for(cost, DEFAULT_K)
            assert c >= prev, f"成本 {cost:.2f} 处积分反而下降"
            prev, cost = c, cost + 0.05

    def test_零成本给零积分(self):
        assert credits_for(0.0, DEFAULT_K) == 0

    def test_取整到整十(self):
        assert credits_for(18.29, DEFAULT_K, round_to=10) % 10 == 0


class TestPriceConsistency:
    """积分单价与积分卡面额必须一致，否则用户按 ¥0.35 心算会算错。"""

    def test_积分单价是0_35(self):
        assert yuan_per_credit(DEFAULT_K) == pytest.approx(0.35)

    def test_积分卡面额与单价一致(self):
        """四张积分卡的面额都按 ¥0.35/积分 定价。"""
        packs = [(80, 28), (260, 91), (770, 270), (2570, 900)]
        for credits, price in packs:
            # 建议定价是取整后的，允许 0.5 元以内的偏差
            assert revenue_for(credits, DEFAULT_K) == pytest.approx(price, abs=0.6), (
                f"{credits} 积分按 ¥0.35 应售 ¥{revenue_for(credits, DEFAULT_K):.2f}，"
                f"但卡面写 ¥{price}"
            )

    def test_常量之间的关系(self):
        """10 积分/元 × 0.25 元 = 2.5 倍成本，这是 0.25 这个数的来历。"""
        assert CREDITS_PER_YUAN_COST * YUAN_PER_CREDIT_UNIT == pytest.approx(2.5)
