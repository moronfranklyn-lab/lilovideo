"""核对「我的账号到底能用哪些模型」。

为什么需要这个模块
------------------
本项目真实踩过一次坑：需要确认方舟上有没有 Seedance 2.5 时，拿**猜的模型 ID**
去调用，收到 `InvalidEndpointOrModel.NotFound`，于是误判"方舟没有这个模型"。
实际上模型就在账号里，只是 ID 写错了（少了版本日期后缀）。

用户会踩一模一样的坑，而且更糟：他们会以为是自己 **Key 填错了**，
然后反复折腾 Key，而不是去看模型 ID。

所以这里做两件事：

1. **列出账号里真实可用的模型**（读平台自己的模型列表接口，不是读我们的静态表）
2. **和当前配置交叉比对**，直接回答"你现在这套配置能不能跑"

端点分别返回两个平台的形状
--------------------------
- 方舟    `GET {base}/models`            → ``{"data": [{"id": ...}]}``
- 百炼    `GET /api/v1/models`           → ``{"output": {"models": [{"model": ...}]}}``

两边字段名不同，这里归一化后再给上层，避免把平台差异泄漏到界面代码里。

只读、不泄漏密钥
----------------
本模块只用**用户自己配置的 Key** 去读他们自己的账号，响应里不回显任何 Key。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Optional

import requests

from config import Config
from models.pricing import get_price

logger = logging.getLogger(__name__)

# 网络超时（秒）。模型列表接口很快，不需要长超时；
# 慢通常意味着网络不通，早点报错比让用户干等好。
TIMEOUT = 20

PROVIDER_ARK = "ark"
PROVIDER_DASHSCOPE = "dashscope"

PROVIDER_LABELS = {
    PROVIDER_ARK: "火山方舟",
    PROVIDER_DASHSCOPE: "阿里云百炼",
}


@dataclass
class AvailabilityResult:
    """一次核对的结果。"""

    provider: str
    ok: bool
    total: int = 0
    model_ids: list[str] = field(default_factory=list)
    model_types: dict[str, str] = field(default_factory=dict)
    error: str = ""
    hint: str = ""

    def to_dict(self) -> dict:
        return {
            "provider": self.provider,
            "provider_label": PROVIDER_LABELS.get(self.provider, self.provider),
            "ok": self.ok,
            "total": self.total,
            "model_ids": sorted(self.model_ids),
            "error": self.error,
            "hint": self.hint,
        }


def _classify_http_error(status: int) -> tuple[str, str]:
    """把 HTTP 状态码翻译成用户能行动的话。

    这一步很重要：原始报错是 "HTTP 401"，用户看不懂该怎么办。
    """
    if status in (401, 403):
        return (
            f"Key 无效或无权限（HTTP {status}）",
            "请确认 Key 复制完整、没有多余空格；也确认该 Key 所属账号已开通对应服务。",
        )
    if status == 404:
        return (
            f"接口地址不对（HTTP 404）",
            "请检查 base_url 是否正确（方舟应为 https://ark.cn-beijing.volces.com/api/v3）。",
        )
    if status == 429:
        return ("请求过于频繁（HTTP 429）", "稍等片刻再试。")
    return (f"平台返回 HTTP {status}", "请稍后重试；若持续失败请检查网络与代理设置。")


def list_ark_models(api_key: Optional[str] = None, base_url: Optional[str] = None) -> AvailabilityResult:
    """列出方舟账号可用的全部模型。"""
    key = api_key or Config.ARK_API_KEY
    base = (base_url or Config.ARK_BASE_URL or "").rstrip("/")
    if not key:
        return AvailabilityResult(
            provider=PROVIDER_ARK, ok=False,
            error="未配置方舟 Key",
            hint="在「设置」页填入 ark.api_key（火山方舟控制台 → API Key）。",
        )
    if not base:
        return AvailabilityResult(
            provider=PROVIDER_ARK, ok=False, error="未配置方舟 base_url")

    try:
        resp = requests.get(
            f"{base}/models",
            headers={"Authorization": f"Bearer {key}"},
            timeout=TIMEOUT,
            proxies=Config.requests_proxies("ark"),
        )
    except requests.RequestException as exc:
        return AvailabilityResult(
            provider=PROVIDER_ARK, ok=False,
            error=f"连接失败：{exc.__class__.__name__}",
            hint="检查网络，或设置代理（api_providers.ark.enable_proxy）。",
        )

    if resp.status_code != 200:
        error, hint = _classify_http_error(resp.status_code)
        return AvailabilityResult(provider=PROVIDER_ARK, ok=False, error=error, hint=hint)

    try:
        rows = resp.json().get("data") or []
    except ValueError:
        return AvailabilityResult(
            provider=PROVIDER_ARK, ok=False,
            error="返回内容不是合法 JSON",
            hint="base_url 可能写错了（应指向 API 地址，不是控制台地址）。",
        )

    ids: list[str] = []
    types: dict[str, str] = {}
    for row in rows:
        mid = row.get("id")
        if not mid:
            continue
        ids.append(mid)
        # 记下任务类型，便于之后按"图/视频/文本"筛选
        task_types = row.get("task_type") or []
        if task_types:
            types[mid] = ",".join(task_types)
    return AvailabilityResult(
        provider=PROVIDER_ARK, ok=True, total=len(ids), model_ids=ids, model_types=types
    )


def list_dashscope_models(api_key: Optional[str] = None) -> AvailabilityResult:
    """列出百炼账号可用的模型。

    分页接口，这里只取前若干页——目的是核对"我配的模型在不在"，
    不需要把 500+ 个全部拉回来。
    """
    key = api_key or Config.DASHSCOPE_API_KEY
    if not key:
        return AvailabilityResult(
            provider=PROVIDER_DASHSCOPE, ok=False,
            error="未配置百炼 Key",
            hint="在「设置」页填入 dashscope.api_key（百炼控制台 → API-KEY 管理）。",
        )

    ids: list[str] = []
    page = 1
    max_pages = 6
    try:
        while page <= max_pages:
            resp = requests.get(
                "https://dashscope.aliyuncs.com/api/v1/models",
                headers={"Authorization": f"Bearer {key}"},
                params={"page_no": page, "page_size": 100},
                timeout=TIMEOUT,
                proxies=Config.requests_proxies("dashscope"),
            )
            if resp.status_code != 200:
                if page == 1:
                    error, hint = _classify_http_error(resp.status_code)
                    return AvailabilityResult(
                        provider=PROVIDER_DASHSCOPE, ok=False, error=error, hint=hint)
                break
            body = resp.json()
            output = body.get("output") or {}
            rows = output.get("models") or []
            for row in rows:
                mid = row.get("model") or row.get("id")
                if mid:
                    ids.append(mid)
            total = int(output.get("total") or 0)
            if not rows or page * 100 >= total:
                break
            page += 1
    except requests.RequestException as exc:
        return AvailabilityResult(
            provider=PROVIDER_DASHSCOPE, ok=False,
            error=f"连接失败：{exc.__class__.__name__}",
            hint="检查网络，或设置代理（api_providers.dashscope.enable_proxy）。",
        )
    except ValueError:
        return AvailabilityResult(
            provider=PROVIDER_DASHSCOPE, ok=False, error="返回内容不是合法 JSON")

    return AvailabilityResult(
        provider=PROVIDER_DASHSCOPE, ok=True, total=len(ids), model_ids=ids
    )


def list_available(provider: str) -> AvailabilityResult:
    if provider == PROVIDER_ARK:
        return list_ark_models()
    if provider == PROVIDER_DASHSCOPE:
        return list_dashscope_models()
    return AvailabilityResult(
        provider=provider, ok=False, error=f"不支持的平台：{provider}")


# ── 把"配置里用到的模型"和"账号里有的模型"对上 ──────────────────────────

def provider_of(model_id: str) -> Optional[str]:
    """判断某个模型由哪个平台提供。

    优先查定价注册表——那里每条都记了 provider，是我们核实过的；
    查不到再按名字前缀兜底（用户可能填了我们没登记的新模型）。
    """
    if not model_id:
        return None
    spec = get_price(model_id)
    if spec is not None:
        return spec.provider
    mid = model_id.lower()
    if any(k in mid for k in ("seedance", "seedream")) or mid.startswith("doubao"):
        return PROVIDER_ARK
    if mid.startswith(("qwen", "wan", "wanx", "happyhorse")):
        return PROVIDER_DASHSCOPE
    return None


# 配置里会用到的模型槽位，以及给用户看的中文名
MODEL_SLOTS: tuple[tuple[str, str], ...] = (
    ("llm", "大语言模型"),
    ("vlm", "视觉理解模型"),
    ("image_t2i", "文生图"),
    ("image_it2i", "图生图"),
    ("video", "视频生成"),
    ("video_first_frame", "首帧生视频"),
    ("video_start_end", "首尾帧生视频"),
    ("video_reference", "参考图生视频"),
)


def check_configured_models() -> dict:
    """核对当前配置里的每个模型槽位，在对应平台的账号里是否真的可用。

    这是本模块最直接的产出：用户填完 Key 点一下，就知道这套配置能不能跑，
    而不是等到某个阶段失败才发现。
    """
    configured: list[dict[str, Any]] = []
    by_provider: dict[str, AvailabilityResult] = {}

    for slot, label in MODEL_SLOTS:
        model_id = getattr(Config, f"{slot.upper()}_MODEL", "") or ""
        provider = provider_of(model_id)
        configured.append({
            "slot": slot,
            "label": label,
            "model_id": model_id,
            "provider": provider,
            "provider_label": PROVIDER_LABELS.get(provider or "", "未知"),
            "available": None,          # 待核对
            "note": "",
        })

    needed = {row["provider"] for row in configured if row["provider"]}
    for provider in sorted(needed):
        by_provider[provider] = list_available(provider)

    for row in configured:
        provider = row["provider"]
        if not provider:
            row["note"] = "无法判断该模型属于哪个平台（可能是自定义模型名）"
            continue
        result = by_provider.get(provider)
        if result is None or not result.ok:
            row["note"] = "平台未核对成功，见下方错误"
            continue
        if row["model_id"] in result.model_ids:
            row["available"] = True
        else:
            row["available"] = False
            row["note"] = (
                "该模型不在你账号的可用列表里。可能是没开通，"
                "也可能是模型 ID 写错（例如少了版本日期后缀）。"
            )

    missing = [r for r in configured if r["available"] is False]
    return {
        "configured": configured,
        "missing": missing,
        "all_available": bool(configured) and not missing and all(
            r["available"] is not None for r in configured
        ),
        "providers": {p: r.to_dict() for p, r in by_provider.items()},
    }
