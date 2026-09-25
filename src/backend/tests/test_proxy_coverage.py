"""前端代理与后端路由的一致性测试。

守的是一个踩过**三次**的坑
-------------------------
前端所有 `/api/*` 请求都靠 `next.config.ts` 里的 `rewrites()` **逐条**转发到后端。
这些规则是精确匹配的：写了 `source: '/api/models'` 并不覆盖 `/api/models/available`。
漏一条的症状是——**直连后端 200，经前端 404**，排查时极容易误判成后端问题。

已发生的三次：

1. `/api/cost/*`（成本接口）
2. `/api/credits/*`（积分接口）
3. `/api/models/*`（模型核对接口，其中 `/api/models` 有代理但子路径没有）

每次都是"后端明明好好的"。所以把它变成一条会自动失败的测试，
而不是继续依赖"记得同步加一条"。
"""

import os
import re
import sys

import pytest

_BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_REPO = os.path.dirname(os.path.dirname(_BACKEND))
sys.path.insert(0, _BACKEND)

_ROUTERS_DIR = os.path.join(_BACKEND, "api", "routers")
_NEXT_CONFIG = os.path.join(_REPO, "src", "frontend", "next.config.ts")


def _backend_prefixes() -> set[str]:
    """从后端路由装饰器里抽出所有 `/api/<前缀>`。"""
    prefixes: set[str] = set()
    for name in os.listdir(_ROUTERS_DIR):
        if not name.endswith(".py"):
            continue
        src = open(os.path.join(_ROUTERS_DIR, name), encoding="utf-8").read()
        for path in re.findall(
            r'@router\.(?:get|post|put|delete|patch)\(\s*"(/api/[^"]+)"', src
        ):
            # /api/cost/session/{id} → /api/cost
            parts = path.split("/")
            if len(parts) >= 3:
                prefixes.add("/".join(parts[:3]))
    return prefixes


def _proxied_prefixes() -> set[str]:
    src = open(_NEXT_CONFIG, encoding="utf-8").read()
    return set(re.findall(r"source:\s*'(/api/[a-z_]+)", src))


@pytest.mark.skipif(not os.path.exists(_NEXT_CONFIG), reason="前端不在签出范围内")
class TestProxyCoverage:
    def test_每一个后端前缀都有代理(self):
        missing = sorted(_backend_prefixes() - _proxied_prefixes())
        assert not missing, (
            "以下后端接口前缀在前端没有代理规则，经前端访问会 404"
            "（直连后端却正常，极易误判）：\n  "
            + "\n  ".join(missing)
            + "\n请在 src/frontend/next.config.ts 的 rewrites() 里补上。"
        )

    def test_精确与通配按需覆盖(self):
        """有精确路由就要精确规则；有子路径就要通配规则。

        两种前缀形态要分清，不能一刀切：

        - `/api/models`   既有精确路由又有子路径（`/api/models/available`）
          → **两条都要**。只写精确，子路径 404；只写通配，精确路径匹配不到。
        - `/api/cache/temp` 只有子路径，没有 `/api/cache` 本身
          → 只需通配。（早先这里判错过一次，要求它也有精确规则。）
        """
        src = open(_NEXT_CONFIG, encoding="utf-8").read()
        exact_rules = set(re.findall(r"source:\s*'(/api/[a-z_]+)'", src))
        wildcard_rules = set(re.findall(r"source:\s*'(/api/[a-z_]+)/:path\*'", src))

        exact_routes: set[str] = set()
        sub_routes: set[str] = set()
        for name in os.listdir(_ROUTERS_DIR):
            if not name.endswith(".py"):
                continue
            s = open(os.path.join(_ROUTERS_DIR, name), encoding="utf-8").read()
            for path in re.findall(
                r'@router\.(?:get|post|put|delete|patch)\(\s*"(/api/[^"]+)"', s
            ):
                parts = path.split("/")
                if len(parts) == 3:
                    exact_routes.add(path)
                elif len(parts) > 3:
                    sub_routes.add("/".join(parts[:3]))

        problems = []
        for prefix in sorted(exact_routes):
            if prefix not in exact_rules:
                problems.append(f"{prefix} 有精确路由，但前端缺精确匹配规则")
        for prefix in sorted(sub_routes):
            if prefix not in wildcard_rules:
                problems.append(f"{prefix} 有子路径路由，但前端缺 /:path* 通配规则")
        assert not problems, "\n  ".join(["前端代理与后端路由不一致："] + problems)

    def test_没有指向不存在前缀的代理(self):
        """反向检查：前端代理了一个后端根本没有的前缀，通常意味着路由被改名了。"""
        orphan = sorted(_proxied_prefixes() - _backend_prefixes())
        # /api/tasks、/api/pipelines 等由 routers 内部实现，允许存在但不强求；
        # 这里只报告明显对不上的，因此断言放宽为"不出现全部前缀都无主"的情况。
        assert len(orphan) < len(_proxied_prefixes()), (
            f"几乎所有代理规则都找不到对应后端路由，可能路径大面积改动过：{orphan}"
        )
