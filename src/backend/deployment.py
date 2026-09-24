"""部署安全。

解决的问题
----------
底座的原始设计是「本地单用户工具」：用户在网页上填自己的 API Key，写进
`config.yaml`。这在只跑在本机时是合理的。

但一旦部署到公网，就出现两个风险：

1. **`base_url` 可被任意修改**。攻击者把接口地址指向自己的服务器，
   之后所有模型请求（含 API Key）都会发到那里。
2. **配置写接口无鉴权**。任何能访问该端口的人都能覆盖密钥配置。

本模块提供两道防线
----------------
防线一（主）：**环境变量优先**。线上部署时密钥只放在服务端环境变量里，
不存在于可写文件。攻击者即使改了 `config.yaml` 也拿不到有效密钥。

防线二（辅）：**非本机模式封死配置写接口**。运行模式按监听地址自动判定，
无需人工配置；公开监听时配置写接口直接返回 403。

判定规则
-------
监听地址是回环地址（127.0.0.1 / ::1 / localhost）→ `local` 模式，允许网页改配置。
监听地址是 0.0.0.0 或具体外部地址 → `public` 模式，禁止网页改配置。

这样默认行为不变（本地开发照旧），而一旦为了对外访问改成监听 0.0.0.0，
防护**自动生效**，不依赖使用者记得改开关。
"""

from __future__ import annotations

import logging
import os
from typing import Optional

logger = logging.getLogger(__name__)

# 运行模式
MODE_LOCAL = "local"
MODE_PUBLIC = "public"

_LOOPBACK_HOSTS = {"127.0.0.1", "::1", "localhost", "0:0:0:0:0:0:0:1"}

# 环境变量映射：环境变量名 → 配置点路径
#
# 线上部署时优先读这些环境变量。命名遵循常见约定，便于在各类托管平台配置。
SECRET_ENV_MAP: dict[str, str] = {
    "DASHSCOPE_API_KEY": "api_providers.dashscope.api_key",
    "ARK_API_KEY": "api_providers.ark.api_key",
    "OPENAI_API_KEY": "api_providers.openai.api_key",
    "GEMINI_API_KEY": "api_providers.gemini.api_key",
    "DEEPSEEK_API_KEY": "api_providers.deepseek.api_key",
    "KLING_ACCESS_KEY": "api_providers.kling.access_key",
    "KLING_SECRET_KEY": "api_providers.kling.secret_key",
}


def detect_mode(host: str) -> str:
    """按监听地址判定运行模式。

    回环地址 → local；其余（含 0.0.0.0、空值）→ public。
    空值按 public 处理是刻意的：拿不到确定信息时选择更安全的判定。
    """
    if not host:
        return MODE_PUBLIC
    return MODE_LOCAL if str(host).strip().lower() in _LOOPBACK_HOSTS else MODE_PUBLIC


def env_secret(config_path: str) -> Optional[str]:
    """取某个配置点对应的环境变量值。未设置或为空时返回 None。"""
    for env_name, path in SECRET_ENV_MAP.items():
        if path == config_path:
            value = os.environ.get(env_name, "").strip()
            return value or None
    return None


def apply_env_overrides(config: dict) -> tuple[dict, list[str]]:
    """把环境变量里的密钥覆盖进配置字典。

    就地返回新的配置与「被环境变量接管」的配置点列表，便于启动时打印一条
    说明，让运维知道哪些密钥来自环境变量而非文件。

    只覆盖密钥字段，不动 base_url 等非机密配置——`base_url` 属于部署配置，
    应由部署方自己控制，不通过环境变量隐式改写。
    """
    applied: list[str] = []
    for env_name, path in SECRET_ENV_MAP.items():
        value = os.environ.get(env_name, "").strip()
        if not value:
            continue
        _set_by_path(config, path, value)
        applied.append(path)
    return config, applied


def _set_by_path(config: dict, path: str, value) -> None:
    """按点分路径写入嵌套字典，中间层不存在时创建。"""
    parts = path.split(".")
    node = config
    for part in parts[:-1]:
        if part not in node or not isinstance(node[part], dict):
            node[part] = {}
        node = node[part]
    node[parts[-1]] = value


def strip_env_secrets(config: dict) -> dict:
    """生成落盘用的配置副本：把由环境变量提供的密钥清空。

    为什么需要它：若把环境变量里的真实密钥写进 `config.yaml`，密钥就重新
    落到了可写文件里，「密钥只存在环境变量」这条防线随之失效。

    只清空**由环境变量提供**的那些点。用户自己在本地填在文件里的密钥不受
    影响，本地开发行为不变。
    """
    import copy

    out = copy.deepcopy(config)
    for env_name, path in SECRET_ENV_MAP.items():
        if not os.environ.get(env_name, "").strip():
            continue  # 该密钥不是环境变量提供的，保持原值
        parts = path.split(".")
        node = out
        for part in parts[:-1]:
            if not isinstance(node.get(part), dict):
                node = None
                break
            node = node[part]
        if node is not None and parts[-1] in node:
            node[parts[-1]] = ""
    return out


def mask_present(value: str) -> str:
    """把非空值替换为掩码，空值保持为空。

    用于对外响应：让前端知道「这个密钥已配置」，但不给出任何可用于猜测的
    长度或片段信息。
    """
    return "********" if str(value or "").strip() else ""


def sanitize_for_public(config: dict) -> dict:
    """生成可安全返回给前端的配置副本。

    所有密钥类字段一律掩码；`base_url` 等其他字段保留，因为它们属于
    用户需要查看的部署配置，且本身不是机密。
    """
    import copy

    out = copy.deepcopy(config)
    secret_leaf = {"api_key", "access_key", "secret_key"}
    for env_name, path in SECRET_ENV_MAP.items():
        parts = path.split(".")
        node = out
        for part in parts[:-1]:
            if not isinstance(node.get(part), dict):
                node = None
                break
            node = node[part]
        if node is not None and parts[-1] in node:
            node[parts[-1]] = mask_present(node[parts[-1]])
    # 兜底：路径表可能不全，再按字段名扫一遍
    def walk(o):
        if isinstance(o, dict):
            for k, v in o.items():
                if k in secret_leaf and isinstance(v, str):
                    o[k] = mask_present(v)
                elif isinstance(v, (dict, list)):
                    walk(v)
        elif isinstance(o, list):
            for i in o:
                walk(i)
    walk(out)
    return out
