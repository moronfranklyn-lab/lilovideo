"""积分接口的测试。

重点不在"能不能返回 200"，而在**资金安全**：
发积分的写接口在公网模式下必须被封死（它没有鉴权，开放等于允许任何人凭空造钱）。
"""

import os
import sys

import pytest
from fastapi.testclient import TestClient

_BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _BACKEND)

from config import Config  # noqa: E402
from models import credits_store as cs  # noqa: E402


@pytest.fixture(autouse=True)
def isolated_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(cs, "CREDITS_DIR", str(tmp_path))
    yield tmp_path


@pytest.fixture(scope="module")
def client():
    from api_server import app
    return TestClient(app)


class TestReadEndpoints:
    def test_账户初始为零(self, client):
        body = client.get("/api/credits/account").json()
        assert body["balance"] == 0
        assert body["locked"] == 0
        assert body["yuan_per_credit"] == 0.35

    def test_账户带出积分价值(self, client):
        """前端不该自己算"这些积分值多少钱"——两边算会算出两个数。"""
        client.post("/api/credits/signup-bonus")
        body = client.get("/api/credits/account").json()
        assert body["balance"] == 300
        assert body["balance_value_yuan"] == 105.0      # 300 × 0.35

    def test_流水分页(self, client):
        client.post("/api/credits/signup-bonus")
        client.post("/api/credits/grant", json={"credits": 260, "reason": "标准卡"})
        body = client.get("/api/credits/ledger?limit=1").json()
        assert body["count"] == 1
        assert body["items"][0]["amount"] == 260

    def test_流水可按会话过滤(self, client):
        cs.grant(cs.LOCAL_USER, 300, "初始")
        cs.reserve(cs.LOCAL_USER, 70, "视频", ref="s1:v", session_id="s1")
        cs.reserve(cs.LOCAL_USER, 42, "视频", ref="s2:v", session_id="s2")
        body = client.get("/api/credits/ledger?session_id=s1").json()
        assert body["count"] == 1
        assert body["items"][0]["session_id"] == "s1"

    def test_对账接口(self, client):
        client.post("/api/credits/signup-bonus")
        body = client.get("/api/credits/verify").json()
        assert body["problems"] == []
        assert body["balance"] == 300


class TestWriteEndpoints:
    def test_注册赠送幂等(self, client):
        client.post("/api/credits/signup-bonus")
        client.post("/api/credits/signup-bonus")
        assert client.get("/api/credits/account").json()["balance"] == 300

    def test_发积分带ref时幂等(self, client):
        client.post("/api/credits/grant", json={"credits": 100, "ref": "order:9"})
        client.post("/api/credits/grant", json={"credits": 100, "ref": "order:9"})
        assert client.get("/api/credits/account").json()["balance"] == 100

    def test_发放负数被拒绝(self, client):
        r = client.post("/api/credits/grant", json={"credits": -100})
        assert r.status_code == 422

    def test_公网模式禁止发积分(self, client, monkeypatch):
        """**这条是资金安全的底线。**

        发积分接口没有鉴权，公网开放等于允许任何人给自己发钱。
        判定依据是运行模式（监听地址推导），不依赖使用者记得关开关。
        """
        monkeypatch.setattr(Config, "IS_PUBLIC", True)
        r = client.post("/api/credits/grant", json={"credits": 10000})
        assert r.status_code == 403
        assert "公网" in r.json()["detail"]
        # 余额不该有任何变化
        monkeypatch.setattr(Config, "IS_PUBLIC", False)
        assert client.get("/api/credits/account").json()["balance"] == 0

    def test_公网模式禁止发注册赠送(self, client, monkeypatch):
        monkeypatch.setattr(Config, "IS_PUBLIC", True)
        r = client.post("/api/credits/signup-bonus")
        assert r.status_code == 403

    def test_公网模式仍可查询(self, client, monkeypatch):
        """读接口可以开放：用户需要看到自己的余额。"""
        monkeypatch.setattr(Config, "IS_PUBLIC", True)
        assert client.get("/api/credits/account").status_code == 200
        assert client.get("/api/credits/ledger").status_code == 200
