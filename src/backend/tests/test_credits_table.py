"""积分换算表的生成一致性测试。

这一组测试守的是**文档与代码不脱节**。

背景：定价文档里的数字必须和运行时用的定价注册表一致。本项目已经踩过坑——
同一份文档里同时写着「免费 300 积分」和「一次闭环需 2,220 积分」。
解决办法是让文档由脚本生成（`docs/阶段文档/credits_table.py`），
但"生成"本身不会自动发生：有人改了 `models/pricing.py` 的价格却忘了重跑脚本，
文档就悄悄过期了。

所以这里跑一次生成，跟磁盘上的 markdown 逐字比对。
不一致就红，并告诉你怎么修。
"""

import importlib.util
import os
import sys

import pytest

_BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # lilovideo/src/backend
_REPO = os.path.dirname(os.path.dirname(_BACKEND))                       # lilovideo/
sys.path.insert(0, _BACKEND)

_DOCS = os.path.join(_REPO, "docs", "阶段文档")
_SCRIPT = os.path.join(_DOCS, "credits_table.py")
_DOC = os.path.join(_DOCS, "积分换算表.md")

# credits_table.py 自己会 `from pricing_calc import ...`（两者同目录）。
# 平时它是被当脚本跑的，所在目录天然在 sys.path 上；用 importlib 加载时不是，
# 所以这里替它补上。
if _DOCS not in sys.path:
    sys.path.insert(0, _DOCS)


def _load_generator():
    """按路径加载 credits_table.py。

    不能用普通 import：它不在 Python 包路径里，而且它自己还会往 sys.path
    里插后端目录（为了 import models.pricing），重复插入会互相干扰。
    用 importlib 按文件路径加载最干净。

    注意必须先塞进 `sys.modules`：`credits_table` 里用了 `@dataclass`，
    而 dataclasses 是靠 `sys.modules[cls.__module__]` 反查模块命名空间的。
    不注册的话会报 `AttributeError: 'NoneType' object has no attribute '__dict__'`。
    """
    spec = importlib.util.spec_from_file_location("credits_table", _SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules["credits_table"] = module
    spec.loader.exec_module(module)
    return module


pytestmark = pytest.mark.skipif(
    not os.path.exists(_SCRIPT), reason="积分换算表生成脚本不在（可能只签出了 src/）"
)


def test_文档与当前定价一致():
    """改了价格就必须重跑 `credits_table.py --write`，否则这里失败。"""
    if not os.path.exists(_DOC):
        pytest.fail(f"缺少 {_DOC}，请运行：python3 credits_table.py --write")

    gen = _load_generator()
    expected = gen.render(k=1.4, seconds=5.0)
    actual = open(_DOC, encoding="utf-8").read()
    assert actual.rstrip("\n") == expected.rstrip("\n"), (
        "积分换算表.md 已过期：与 models/pricing.py 的当前价格或换算公式不一致。\n"
        "修复：cd docs/阶段文档 && python3 credits_table.py --write"
    )


def test_所有可售档位都出现在文档里():
    """防御：注册表里新增了模型，但文档没跟上。"""
    gen = _load_generator()
    skus = gen.build_skus(k=1.4, seconds=5.0)
    doc = open(_DOC, encoding="utf-8").read()
    for sku in skus:
        assert sku.display in doc, f"{sku.model_id}（{sku.display}）没有出现在积分换算表里"


def test_已发布五档的积分未被取整规则改动():
    """回归：积分取整改用 Decimal 后，已公布的五档数值必须一字不变。

    这四个数值同时写在《组合计价.md》《积分与会员模型.md》和产品对外口径里，
    改动会造成用户侧不一致。
    """
    from pricing_calc import credits_for

    published = {
        "wan2.6-i2v-flash|720P 无声": (0.75, 10),
        "wan2.6-i2v-flash|720P 带音": (1.50, 21),
        "wan2.7-i2v|720P": (3.00, 42),
        "doubao-seedance-2-0-fast-260128|720P": (4.03, 56),
        "doubao-seedance-2-0-260128|720P": (5.01, 70),
    }
    for key, (cost, expected) in published.items():
        assert credits_for(cost, 1.4) == expected, f"{key} 的积分从 {expected} 变了"
