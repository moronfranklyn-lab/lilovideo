"""可售视频档位目录与报价接口的测试。

覆盖三件事：
1. 目录本身自洽（积分与成本对得上、按价格排序、档位不重复）
2. 两大平台都被覆盖（漏掉任何一个平台都是产品级事故）
3. 报价接口在"算不出来"时必须说 `known=false`，**不能悄悄退回默认档**
"""

import os
import sys

import pytest

_BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _BACKEND)

from models.credits import DEFAULT_K, credits_for  # noqa: E402
from models.video_catalog import (  # noqa: E402
    VENDOR_ARK,
    VENDOR_DASHSCOPE,
    find_sku,
    list_video_skus,
)


@pytest.fixture(scope="module")
def skus():
    return list_video_skus(k=DEFAULT_K, seconds=5.0)


class TestCatalog:
    def test_两个平台都有档位(self, skus):
        vendors = {s.vendor for s in skus}
        assert vendors == {VENDOR_DASHSCOPE, VENDOR_ARK}

    def test_档位总数(self, skus):
        """31 = 通义 25 档（10 个模型各自的分辨率/音轨）+ 豆包 6 档。

        豆包 6 档 = 2.0 Mini 720P、2.0 Fast 720P、2.0 720P +
        Seedance 2.5 的 480P / 720P / 1080P。
        （2.0 系只取到 720P 的费率，所以不编 480P/1080P 的价。）

        这个数字变了不一定是错——加了新模型就会变。
        但必须是有意为之：改了价格表就该重跑 credits_table.py 并更新文档。
        """
        assert len(skus) == 31
        assert len({s.key for s in skus}) == 31, "档位 key 重复"

    def test_积分与成本对得上(self, skus):
        for s in skus:
            assert s.credits == credits_for(s.cost, DEFAULT_K), f"{s.key} 积分与成本不符"

    def test_每个档位都有正的成本与积分(self, skus):
        for s in skus:
            assert s.cost > 0, f"{s.key} 成本不为正"
            assert s.credits > 0, f"{s.key} 积分为 0，用户会以为免费"

    def test_按每秒成本可排序(self, skus):
        ordered = sorted(skus, key=lambda s: s.per_second)
        assert ordered[0].per_second < ordered[-1].per_second

    def test_最便宜档是特价档(self, skus):
        cheapest = min(skus, key=lambda s: s.cost)
        assert cheapest.model_id == "wan2.6-i2v-flash"
        assert cheapest.label == "720P 无声"
        assert cheapest.credits == 10

    def test_豆包侧四个档位型号齐全(self, skus):
        ark = {s.model_id for s in skus if s.vendor == VENDOR_ARK}
        assert ark == {
            "doubao-seedance-2-5-260628",
            "doubao-seedance-2-0-260128",
            "doubao-seedance-2-0-fast-260128",
            "doubao-seedance-2-0-mini-260615",
        }

    def test_豆包侧各档每秒成本互不相同(self, skus):
        """回归：曾经 mini / fast / 标准 全被当成 1 元/秒。

        数值按官方公式（108,000 tokens / 5 秒 = 21,600 tokens/秒）算出。
        """
        ark = {}
        for s in skus:
            if s.vendor != VENDOR_ARK or s.label != "720P":
                continue
            ark[s.model_id] = s.per_second
        assert ark["doubao-seedance-2-0-mini-260615"] == pytest.approx(0.50, abs=0.01)
        assert ark["doubao-seedance-2-0-fast-260128"] == pytest.approx(0.80, abs=0.01)
        assert ark["doubao-seedance-2-0-260128"] == pytest.approx(0.99, abs=0.01)
        assert ark["doubao-seedance-2-5-260628"] == pytest.approx(1.51, abs=0.01)
        assert len(set(round(v, 2) for v in ark.values())) == len(ark)

    def test_豆包侧唯独2_5有三档分辨率(self, skus):
        """2.5 取到了三档费率，其余只取到 720P。"""
        by_model = {}
        for s in skus:
            if s.vendor == VENDOR_ARK:
                by_model.setdefault(s.model_id, set()).add(s.label)
        assert by_model["doubao-seedance-2-5-260628"] == {"480P", "720P", "1080P"}
        assert by_model["doubao-seedance-2-0-260128"] == {"720P"}

    def test_1080P报价高于720P(self, skus):
        """1080P 的 tokens 是 720P 的 2.25 倍，费率还高 10%，所以明显更贵。"""
        two_five = {s.label: s for s in skus if s.model_id == "doubao-seedance-2-5-260628"}
        assert two_five["1080P"].credits > two_five["720P"].credits * 2

    def test_通义侧不出现重复的模型加档位(self, skus):
        keys = [s.key for s in skus if s.vendor == VENDOR_DASHSCOPE]
        assert len(keys) == len(set(keys))

    def test_按模型加档位查找(self):
        s = find_sku("wan2.6-i2v-flash", "1080P 带音")
        assert s is not None and s.credits == 35
        assert find_sku("wan2.6-i2v-flash", "4K 带音") is None
        assert find_sku("不存在的模型", "720P") is None


@pytest.fixture(scope="module")
def client():
    """整个模块共用一个 TestClient（导入 app 有开销，不必每个测试重建）。"""
    from fastapi.testclient import TestClient
    from api_server import app
    return TestClient(app)


class TestEstimateApi:
    def test_档位目录接口(self, client):
        r = client.get("/api/cost/video-models")
        assert r.status_code == 200
        body = r.json()
        assert body["count"] == 31
        # 毛利由代码给出，不再靠文档声明
        assert body["margin"] == pytest.approx(0.796, abs=0.001)
        assert body["markup"] == pytest.approx(4.90, abs=0.01)
        costs = [i["cost"] for i in body["items"]]
        assert costs == sorted(costs), "接口应按成本升序返回，最便宜的在前"

    def test_指定档位能报出正确积分(self, client):
        r = client.post("/api/cost/estimate", json={
            "model_id": "wan2.6-i2v-flash", "seconds": 5, "variant": "720P 带音",
        })
        body = r.json()
        assert body["known"] is True
        assert body["credits"] == 21
        assert body["amount"] == pytest.approx(1.50)

    def test_不存在的档位报未知而不是退回默认档(self, client):
        """关键防御：用户选了 4K，不能按 720P 给他报价。"""
        r = client.post("/api/cost/estimate", json={
            "model_id": "wan2.6-i2v-flash", "seconds": 5, "variant": "4K 带音",
        })
        body = r.json()
        assert body["known"] is False
        assert "credits" not in body

    def test_seedance报价标记为未核实(self, client):
        r = client.post("/api/cost/estimate", json={
            "model_id": "doubao-seedance-2-0-260128", "seconds": 5,
        })
        body = r.json()
        assert body["known"] is True
        assert body["verified"] is False, "tokens 换算是估计，不能标为已核实"
        assert body["credits"] == 70

    def test_通义报价标记为已核实(self, client):
        r = client.post("/api/cost/estimate", json={"model_id": "wan2.7-i2v", "seconds": 5})
        body = r.json()
        assert body["known"] is True
        assert body["verified"] is True

    def test_秒数必须为正(self, client):
        r = client.post("/api/cost/estimate", json={"model_id": "wan2.7-i2v", "seconds": 0})
        assert r.status_code == 422
