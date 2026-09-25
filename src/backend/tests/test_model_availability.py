"""模型可用性核对的测试。

重点是**错误分类**：用户分不清"Key 填错了"和"模型 ID 写错了"，
而这两件事的处理方式完全不同。所以每条错误路径都要有对应的、
能指导行动的提示，而不是把原始 HTTP 状态码丢给用户。

全部用假响应，不联网。
"""

import os
import sys

import pytest
import requests

_BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _BACKEND)

from models import model_availability as ma  # noqa: E402


class FakeResponse:
    def __init__(self, status_code=200, payload=None, text=""):
        self.status_code = status_code
        self._payload = payload
        self.text = text

    def json(self):
        if self._payload is None:
            raise ValueError("not json")
        return self._payload


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    """本文件的测试一律不许联网。

    这个模块是唯一会主动访问外部平台的，一旦某个用例忘了 patch，
    就会真的打出去——慢、不稳定，还可能因为本地配了真实 Key 而"假通过"。
    所以默认把 requests.get 换成直接报错，需要的用例再自己覆盖。
    """
    def boom(*a, **kw):
        raise AssertionError("测试禁止联网：请在本用例里 patch ma.requests.get")
    monkeypatch.setattr(ma.requests, "get", boom)


@pytest.fixture
def with_keys(monkeypatch):
    monkeypatch.setattr(ma.Config, "ARK_API_KEY", "fake-ark-key")
    monkeypatch.setattr(ma.Config, "ARK_BASE_URL", "https://ark.example.com/api/v3")
    monkeypatch.setattr(ma.Config, "DASHSCOPE_API_KEY", "fake-ds-key")


def _patch_get(monkeypatch, response=None, exc=None):
    def fake_get(*a, **kw):
        if exc is not None:
            raise exc
        return response
    monkeypatch.setattr(ma.requests, "get", fake_get)


class TestArkListing:
    def test_正常列出(self, monkeypatch, with_keys):
        _patch_get(monkeypatch, FakeResponse(200, {"data": [
            {"id": "doubao-seedance-2-0-260128", "task_type": ["MultimodalToVideo"]},
            {"id": "deepseek-v4-1-flash-260910", "task_type": ["TextGeneration"]},
        ]}))
        r = ma.list_ark_models()
        assert r.ok and r.total == 2
        assert "deepseek-v4-1-flash-260910" in r.model_ids
        assert "TextGeneration" in r.model_types["deepseek-v4-1-flash-260910"]

    def test_未配置Key给出可行动提示(self, monkeypatch):
        # 注意：传 api_key="" 会**回退到配置里的 Key**，模拟不出"没配 Key"。
        # 必须直接改配置，才是用户真实遇到的场景。
        monkeypatch.setattr(ma.Config, "ARK_API_KEY", "")
        r = ma.list_ark_models()
        assert not r.ok
        assert "未配置" in r.error
        assert "设置" in r.hint

    def test_401翻译成Key问题(self, monkeypatch, with_keys):
        _patch_get(monkeypatch, FakeResponse(401))
        r = ma.list_ark_models()
        assert not r.ok
        assert "Key 无效" in r.error
        assert "复制完整" in r.hint          # 要能指导用户怎么做

    def test_404翻译成地址问题(self, monkeypatch, with_keys):
        """404 是 base_url 写错，不是 Key 错——两者必须区分开。"""
        _patch_get(monkeypatch, FakeResponse(404))
        r = ma.list_ark_models()
        assert not r.ok
        assert "接口地址" in r.error
        assert "ark.cn-beijing.volces.com" in r.hint

    def test_429翻译成频率问题(self, monkeypatch, with_keys):
        _patch_get(monkeypatch, FakeResponse(429))
        r = ma.list_ark_models()
        assert "频繁" in r.error

    def test_非JSON提示base_url可能写错(self, monkeypatch, with_keys):
        _patch_get(monkeypatch, FakeResponse(200, payload=None))
        r = ma.list_ark_models()
        assert not r.ok
        assert "JSON" in r.error
        assert "base_url" in r.hint

    def test_网络异常不抛栈(self, monkeypatch, with_keys):
        _patch_get(monkeypatch, exc=requests.ConnectionError("boom"))
        r = ma.list_ark_models()
        assert not r.ok
        assert "连接失败" in r.error
        assert "代理" in r.hint

    def test_响应里不含密钥(self, monkeypatch, with_keys):
        """核对结果会直接回给前端，绝不能把密钥带出去。"""
        _patch_get(monkeypatch, FakeResponse(200, {"data": [{"id": "m1"}]}))
        payload = str(ma.list_ark_models().to_dict())
        assert "fake-ark-key" not in payload


class TestDashscopeListing:
    def test_正常列出与分页(self, monkeypatch, with_keys):
        pages = {
            1: {"output": {"total": 150, "models": [{"model": "qwen-max"}]}},
            2: {"output": {"total": 150, "models": [{"model": "wan2.6-i2v"}]}},
        }

        def fake_get(url, params=None, **kw):
            return FakeResponse(200, pages.get(params.get("page_no"), {"output": {"total": 150, "models": []}}))

        monkeypatch.setattr(ma.requests, "get", fake_get)
        r = ma.list_dashscope_models()
        assert r.ok
        assert set(r.model_ids) == {"qwen-max", "wan2.6-i2v"}

    def test_未配置Key(self, monkeypatch):
        monkeypatch.setattr(ma.Config, "DASHSCOPE_API_KEY", "")
        r = ma.list_dashscope_models()
        assert not r.ok and "未配置" in r.error

    def test_首屏401直接返回错误(self, monkeypatch, with_keys):
        monkeypatch.setattr(ma.requests, "get",
                            lambda *a, **kw: FakeResponse(401))
        r = ma.list_dashscope_models()
        assert not r.ok and "Key 无效" in r.error


class TestProviderDetection:
    def test_注册表优先(self):
        # 定价注册表里记的是权威答案
        assert ma.provider_of("doubao-seedance-2-0-260128") == "ark"
        assert ma.provider_of("wan2.7-i2v") == "dashscope"
        assert ma.provider_of("deepseek-v4-1-flash-260910") == "ark"

    def test_未登记时按名字兜底(self):
        assert ma.provider_of("doubao-something-new-260101") == "ark"
        assert ma.provider_of("qwen9-turbo") == "dashscope"
        assert ma.provider_of("happyhorse-9.9-i2v") == "dashscope"

    def test_认不出返回None(self):
        assert ma.provider_of("totally-unknown-model") is None
        assert ma.provider_of("") is None


class TestConfiguredCheck:
    def test_模型不在账号里会被标出来(self, monkeypatch, with_keys):
        """核心场景：配置里的模型账号没有 → 必须明确指出，并说明可能原因。"""
        monkeypatch.setattr(ma, "list_available", lambda p: ma.AvailabilityResult(
            provider=p, ok=True, total=1,
            model_ids=(["doubao-seedance-2-0-260128", "doubao-seedream-4-0-250828"]
                       if p == "ark" else ["qwen3.7-plus"]),
        ))
        r = ma.check_configured_models()
        assert not r["all_available"]
        # 视频槽位配的是方舟模型且存在 → 可用
        video = next(x for x in r["configured"] if x["slot"] == "video")
        assert video["available"] is True

    def test_账号缺模型时给出原因(self, monkeypatch, with_keys):
        monkeypatch.setattr(ma, "list_available", lambda p: ma.AvailabilityResult(
            provider=p, ok=True, total=0, model_ids=[]))
        r = ma.check_configured_models()
        assert len(r["missing"]) == len(r["configured"])
        note = r["missing"][0]["note"]
        assert "没开通" in note and "版本日期后缀" in note

    def test_平台核对失败时不误报为缺模型(self, monkeypatch, with_keys):
        """核对失败必须与"模型不存在"区分开，否则会误导用户去改模型 ID。"""
        monkeypatch.setattr(ma, "list_available", lambda p: ma.AvailabilityResult(
            provider=p, ok=False, error="Key 无效或无权限（HTTP 401）"))
        r = ma.check_configured_models()
        assert r["missing"] == [], "核对失败不该被当成缺模型"
        assert all(row["available"] is None for row in r["configured"])
        assert "核对成功" in r["configured"][0]["note"]

    def test_不可判定的模型有单独说明(self, monkeypatch, with_keys):
        monkeypatch.setattr(ma.Config, "LLM_MODEL", "custom-model-x", raising=False)
        monkeypatch.setattr(ma, "list_available", lambda p: ma.AvailabilityResult(
            provider=p, ok=True, total=0, model_ids=[]))
        r = ma.check_configured_models()
        row = next(x for x in r["configured"] if x["slot"] == "llm")
        assert row["provider"] is None
        assert "无法判断" in row["note"]


@pytest.fixture(scope="module")
def client():
    from fastapi.testclient import TestClient
    from api_server import app
    return TestClient(app)


class TestEndpoint:
    def test_非法平台返回422(self, client):
        r = client.get("/api/models/available?provider=nope")
        assert r.status_code == 422
        assert "不支持的平台" in r.json()["detail"]

    def test_平台参数必填(self, client):
        assert client.get("/api/models/available").status_code == 422
