"""配置接口。

安全设计（重要）
---------------
底座的原始设计是本地单用户工具：用户在网页上填自己的 API Key，只跑在本机时
这没问题。但部署到公网后有两个风险，本文件负责封堵：

1. **写接口无鉴权** → `public` 模式下直接返回 403，配置不可从网页修改
2. **响应泄漏密钥** → 所有响应统一走脱敏，密钥字段只回 `********`

运行模式由监听地址自动判定（见 `deployment.py`）：监听 `0.0.0.0` 时防护
自动生效，不依赖使用者记得改开关。
"""

from typing import Any, Dict

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from api.logging_config import apply_access_log_setting, apply_log_level_setting
from config import Config
from deployment import sanitize_for_public

router = APIRouter(tags=["Configuration"])


class ConfigUpdateRequest(BaseModel):
    values: Dict[str, Any] = Field(default_factory=dict)


def _public_payload() -> Dict[str, Any]:
    """对外返回的配置：密钥一律脱敏，并告知当前模式是否可写。"""
    return {
        "config": sanitize_for_public(Config.CONFIG),
        "path": "backend/config.yaml",
        "mode": Config.MODE,
        "config_writable": not Config.IS_PUBLIC,
    }


@router.get("/api/config")
async def get_config():
    return _public_payload()


@router.put("/api/config")
async def update_config(req: ConfigUpdateRequest):
    """更新配置。

    仅在 `local` 模式（监听回环地址）下允许。公网部署时密钥应通过服务端
    环境变量提供，网页不得修改配置——否则任何人都能改写 `base_url`，把
    模型请求（连同密钥）重定向到自己的服务器。
    """
    if Config.IS_PUBLIC:
        raise HTTPException(
            status_code=403,
            detail=(
                "当前为公开部署模式，配置不可从网页修改。"
                "请通过服务端环境变量提供密钥，参见 docs/部署说明.md。"
            ),
        )

    Config.update_config(req.values)
    apply_log_level_setting()
    apply_access_log_setting()
    return _public_payload()
