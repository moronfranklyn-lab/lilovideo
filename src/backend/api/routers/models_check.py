"""模型可用性核对接口。

回答一个具体问题：**「我填的 Key 到底能不能跑当前这套配置？」**

为什么需要它：用户填完 Key 之后没有任何反馈渠道，只能等到某个阶段跑失败。
而失败信息通常是平台返回的原始错误，很容易被误读成"Key 填错了"——
实际上更常见的原因是**模型 ID 不在自己账号里**（本项目自己就踩过：
拿猜的模型 ID 去调，收到 NotFound，误判成"平台没有这个模型"）。

只读接口，不写入任何配置，也不回显密钥。
"""

from fastapi import APIRouter, HTTPException, Query

from models.model_availability import (
    PROVIDER_ARK,
    PROVIDER_DASHSCOPE,
    check_configured_models,
    list_available,
)

router = APIRouter(tags=["Models"])

_SUPPORTED = (PROVIDER_ARK, PROVIDER_DASHSCOPE)


@router.get("/api/models/available")
async def get_available_models(
    provider: str = Query(..., description="平台：ark | dashscope"),
):
    """列出某个平台**账号里真实可用**的模型。

    注意与 `/api/models` 的区别：那个返回的是**本程序支持**哪些模型（静态表），
    这个返回的是**你的账号能用**哪些模型（实调平台接口）。
    两者不一致时，就是配置会失败的地方。
    """
    if provider not in _SUPPORTED:
        raise HTTPException(
            status_code=422,
            detail=f"不支持的平台：{provider}。可选：{'、'.join(_SUPPORTED)}",
        )
    return list_available(provider).to_dict()


@router.get("/api/models/check")
async def check_models():
    """核对当前配置里的每个模型槽位是否真的可用。

    这是设置页「核对可用模型」按钮背后的接口：一次调用同时核对两个平台，
    并逐槽位给出「可用 / 不可用 / 无法判断」，附上可以行动的建议。
    """
    return check_configured_models()
