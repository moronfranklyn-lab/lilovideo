"""部署安全测试。

守住三条不能退让的性质：
1. 公网模式（监听非回环地址）必须封死配置写接口
2. 密钥绝不因响应而泄漏
3. 环境变量提供的密钥不得被写回可写文件，也不得被配置写入覆盖
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from deployment import (  # noqa: E402
    MODE_LOCAL,
    MODE_PUBLIC,
    apply_env_overrides,
    detect_mode,
    env_secret,
    mask_present,
    sanitize_for_public,
    strip_env_secrets,
)


class TestModeDetection:
    @pytest.mark.parametrize("host", ["127.0.0.1", "localhost", "::1", "LOCALHOST", " 127.0.0.1 "])
    def test_回环地址判为本地(self, host):
        assert detect_mode(host) == MODE_LOCAL

    @pytest.mark.parametrize("host", ["0.0.0.0", "192.168.1.5", "10.0.0.1", "", None])
    def test_非回环判为公网(self, host):
        """空值也判为公网：拿不到确定信息时选更安全的判定。"""
        assert detect_mode(host) == MODE_PUBLIC

    def test_默认防护不依赖人工开关(self):
        """关键性质：为了对外访问改成 0.0.0.0，防护必须自动生效。"""
        assert detect_mode("0.0.0.0") == MODE_PUBLIC


class TestMasking:
    def test_有值掩码_无值保持空(self):
        assert mask_present("sk-real-key") == "********"
        assert mask_present("") == ""
        assert mask_present("   ") == ""
        assert mask_present(None) == ""

    def test_掩码不泄漏长度与片段(self):
        """掩码必须是固定长度，不能让人推测出密钥长度。"""
        assert mask_present("a") == mask_present("a" * 200)

    def test_脱敏覆盖所有密钥字段(self):
        cfg = {
            "api_providers": {
                "dashscope": {"api_key": "sk-real-dashscope", "base_url": "https://x"},
                "ark": {"api_key": "ark-real", "base_url": "https://y"},
                "kling": {"access_key": "ak", "secret_key": "sk"},
                # 未在映射表里的字段也要被兜底扫到
                "unknown": {"api_key": "another-secret"},
            }
        }
        out = sanitize_for_public(cfg)
        assert out["api_providers"]["dashscope"]["api_key"] == "********"
        assert out["api_providers"]["ark"]["api_key"] == "********"
        assert out["api_providers"]["kling"]["access_key"] == "********"
        assert out["api_providers"]["kling"]["secret_key"] == "********"
        assert out["api_providers"]["unknown"]["api_key"] == "********"
        # 非机密字段保留，用户需要看到
        assert out["api_providers"]["dashscope"]["base_url"] == "https://x"

    def test_脱敏不修改原配置(self):
        cfg = {"api_providers": {"ark": {"api_key": "real"}}}
        sanitize_for_public(cfg)
        assert cfg["api_providers"]["ark"]["api_key"] == "real"


class TestEnvOverride:
    def test_环境变量覆盖生效(self, monkeypatch):
        monkeypatch.setenv("ARK_API_KEY", "from-env")
        cfg = {"api_providers": {"ark": {"api_key": "from-file"}}}
        out, applied = apply_env_overrides(cfg)
        assert out["api_providers"]["ark"]["api_key"] == "from-env"
        assert "api_providers.ark.api_key" in applied

    def test_未设环境变量时不改动(self, monkeypatch):
        monkeypatch.delenv("ARK_API_KEY", raising=False)
        cfg = {"api_providers": {"ark": {"api_key": "from-file"}}}
        out, applied = apply_env_overrides(cfg)
        assert out["api_providers"]["ark"]["api_key"] == "from-file"
        assert applied == []

    def test_空字符串环境变量视为未设置(self, monkeypatch):
        monkeypatch.setenv("ARK_API_KEY", "   ")
        cfg = {"api_providers": {"ark": {"api_key": "from-file"}}}
        out, _ = apply_env_overrides(cfg)
        assert out["api_providers"]["ark"]["api_key"] == "from-file"

    def test_中间层缺失时能创建(self, monkeypatch):
        monkeypatch.setenv("GEMINI_API_KEY", "g")
        cfg = {}
        out, _ = apply_env_overrides(cfg)
        assert out["api_providers"]["gemini"]["api_key"] == "g"

    def test_env_secret_查询(self, monkeypatch):
        monkeypatch.setenv("DASHSCOPE_API_KEY", "d")
        assert env_secret("api_providers.dashscope.api_key") == "d"
        assert env_secret("api_providers.ark.api_key") is None


class TestStripEnvSecrets:
    def test_环境变量来源的密钥不落盘(self, monkeypatch):
        """关键：环境变量提供的密钥必须从落盘副本里清空，否则防线失效。"""
        monkeypatch.setenv("ARK_API_KEY", "from-env")
        cfg = {"api_providers": {"ark": {"api_key": "from-env", "base_url": "https://x"}}}
        out = strip_env_secrets(cfg)
        assert out["api_providers"]["ark"]["api_key"] == ""
        # 非密钥字段保留
        assert out["api_providers"]["ark"]["base_url"] == "https://x"

    def test_用户自填的密钥不被清空(self, monkeypatch):
        """本地开发时用户自己填在文件里的密钥不能被误删。"""
        monkeypatch.delenv("ARK_API_KEY", raising=False)
        cfg = {"api_providers": {"ark": {"api_key": "user-filled"}}}
        out = strip_env_secrets(cfg)
        assert out["api_providers"]["ark"]["api_key"] == "user-filled"

    def test_不修改原配置(self, monkeypatch):
        monkeypatch.setenv("ARK_API_KEY", "from-env")
        cfg = {"api_providers": {"ark": {"api_key": "from-env"}}}
        strip_env_secrets(cfg)
        # strip 后内存里仍需保留真实值供本次运行使用
        assert cfg["api_providers"]["ark"]["api_key"] == "from-env"

    def test_写盘与内存分离的完整流程(self, monkeypatch):
        """模拟 update_config：落盘不含密钥，内存含密钥。"""
        monkeypatch.setenv("ARK_API_KEY", "from-env")
        incoming = {"api_providers": {"ark": {"api_key": "attacker-value"}}}

        to_disk = strip_env_secrets(incoming)
        assert to_disk["api_providers"]["ark"]["api_key"] == ""

        in_memory, _ = apply_env_overrides(to_disk)
        # 攻击者写入的值既没落盘，也没能覆盖环境变量
        assert in_memory["api_providers"]["ark"]["api_key"] == "from-env"
