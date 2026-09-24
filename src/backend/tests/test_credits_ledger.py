"""积分账户与流水的测试。

这一组盯的是**资金安全**，所以比一般单测更强调不变式与边界：

1. 余额**永不为负**
2. 预扣/结算/退回都**幂等**（重试与连点不能重复扣费）
3. 账本自洽：`sum(amount) == balance`，且每笔的 `balance_after` 都能串起来
4. `total_consumed` 的口径正确：预扣中不算、已退回不算、退还的差额要扣掉

第 3、4 条对应两个真实写出来过的 bug（`balance_after` 从没写入、
结算后派生值没重算），所以这里的断言不是形式主义。
"""

import os
import sys
import threading

import pytest

_BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _BACKEND)

from models import credits_store as cs  # noqa: E402


@pytest.fixture(autouse=True)
def isolated_dir(tmp_path, monkeypatch):
    """账本写到临时目录，绝不碰真实账本。

    **这一点很关键**：真实账本是用户的钱。测试若误写到真实目录，
    一次 `grant` 就能给账户凭空发积分。
    """
    monkeypatch.setattr(cs, "CREDITS_DIR", str(tmp_path))
    yield tmp_path


@pytest.fixture
def user():
    cs.grant_signup_bonus(cs.LOCAL_USER)
    return cs.LOCAL_USER


class TestGrant:
    def test_注册赠送三百(self, isolated_dir):
        cs.grant_signup_bonus(cs.LOCAL_USER)
        a = cs.get_account()
        assert a["balance"] == 300
        assert a["total_granted"] == 300
        assert a["total_consumed"] == 0

    def test_注册赠送重复调用只发一次(self):
        first = cs.grant_signup_bonus(cs.LOCAL_USER)
        second = cs.grant_signup_bonus(cs.LOCAL_USER)
        assert first["id"] == second["id"]
        assert cs.get_account()["balance"] == 300, "幂等失效，赠送发了两次"

    def test_入账必须为正(self):
        with pytest.raises(cs.CreditsError):
            cs.grant(cs.LOCAL_USER, 0, "零")
        with pytest.raises(cs.CreditsError):
            cs.grant(cs.LOCAL_USER, -10, "负数")

    def test_购买与赠送分开记账(self):
        cs.grant(cs.LOCAL_USER, 100, "买卡", type_=cs.TYPE_PURCHASE)
        a = cs.get_account()
        assert a["balance"] == 100
        assert a["total_granted"] == 100


class TestReserve:
    def test_预扣减少余额并挂起(self, user):
        txn = cs.reserve(user, 70, "视频 5 秒", ref="s1:video", session_id="s1")
        assert txn["status"] == cs.STATUS_PENDING
        a = cs.get_account()
        assert a["balance"] == 230
        assert a["locked"] == 70
        assert a["total_consumed"] == 0, "预扣中的钱还没真正花掉，不该算消耗"

    def test_余额不足直接拒绝而不是透支(self):
        cs.grant(cs.LOCAL_USER, 50, "少量")
        with pytest.raises(cs.InsufficientCredits) as exc:
            cs.reserve(cs.LOCAL_USER, 70, "买不起", ref="nope")
        assert exc.value.shortfall == 20
        assert cs.get_account()["balance"] == 50, "被拒绝的预扣不该改动余额"

    def test_同一ref重复预扣不重复扣费(self, user):
        a = cs.reserve(user, 42, "重试", ref="same")
        b = cs.reserve(user, 42, "重试", ref="same")
        assert a["id"] == b["id"]
        assert cs.get_account()["balance"] == 258, "重复预扣扣了两次"

    def test_ref必填(self, user):
        with pytest.raises(cs.CreditsError):
            cs.reserve(user, 10, "无 ref", ref="")


class TestSettle:
    def test_实际少于预扣要退还差额(self, user):
        cs.reserve(user, 70, "视频", ref="s1:v")
        cs.settle("s1:v", 56)
        a = cs.get_account()
        assert a["balance"] == 244          # 300 - 56
        assert a["total_consumed"] == 56    # 只有 56 算消耗，不是 70
        assert a["locked"] == 0

    def test_实际多于预扣要补扣(self, user):
        cs.reserve(user, 10, "视频", ref="s1:v")
        cs.settle("s1:v", 35)
        a = cs.get_account()
        assert a["balance"] == 265          # 300 - 35
        assert a["total_consumed"] == 35

    def test_金额相同直接确认(self, user):
        cs.reserve(user, 42, "视频", ref="s1:v")
        cs.settle("s1:v", 42)
        a = cs.get_account()
        assert a["balance"] == 258
        assert a["total_consumed"] == 42
        assert a["locked"] == 0

    def test_重复结算幂等(self, user):
        cs.reserve(user, 70, "视频", ref="s1:v")
        cs.settle("s1:v", 56)
        cs.settle("s1:v", 56)
        cs.settle("s1:v", 999)              # 第二次起一律忽略
        assert cs.get_account()["balance"] == 244

    def test_补扣超出余额时记缺口且不透支(self):
        """资金安全边界：实际用量超出预扣且余额不足。

        不能透支，也不能把缺口藏起来——扣到 0，缺口写进流水的 shortfall。

        这里的算术要算清楚：预扣 10 已经扣走了，补扣只能再扣余额里剩的 10，
        所以真正收到的是 20，相对实际 100 的缺口是 **80**（不是 90）。
        """
        cs.grant(cs.LOCAL_USER, 20, "很少")
        cs.reserve(cs.LOCAL_USER, 10, "视频", ref="s1:v")
        txn = cs.settle("s1:v", 100)
        a = cs.get_account()
        assert a["balance"] == 0, "余额不允许为负"
        assert a["total_consumed"] == 20, "实际收到的只有 20"
        assert txn["shortfall"] == 80, "缺口必须被记下来"
        assert cs.verify(cs.LOCAL_USER)["problems"] == []

    def test_结算不存在的ref报错(self, user):
        with pytest.raises(cs.CreditsError):
            cs.settle("从没预扣过", 10)


class TestRelease:
    def test_退回全额返还(self, user):
        cs.reserve(user, 106, "视频 2.5", ref="s1:v")
        cs.release("s1:v", reason="阶段失败")
        a = cs.get_account()
        assert a["balance"] == 300
        assert a["total_consumed"] == 0, "退回的不该算消耗"
        assert a["locked"] == 0

    def test_重复退回幂等(self, user):
        cs.reserve(user, 106, "视频", ref="s1:v")
        cs.release("s1:v")
        cs.release("s1:v")
        assert cs.get_account()["balance"] == 300

    def test_已结算的不能再退回(self, user):
        cs.reserve(user, 70, "视频", ref="s1:v")
        cs.settle("s1:v", 56)
        with pytest.raises(cs.CreditsError):
            cs.release("s1:v")

    def test_退回后原流水保留为历史(self, user):
        cs.reserve(user, 106, "视频", ref="s1:v")
        cs.release("s1:v")
        ledger = cs.get_ledger()
        original = [t for t in ledger if t.get("ref") == "s1:v"][0]
        assert original["status"] == cs.STATUS_RELEASED
        assert original["amount"] == -106, "退回靠新增反向流水，不改原记录"


class TestLedgerIntegrity:
    def test_余额等于流水之和(self, user):
        cs.reserve(user, 70, "视频", ref="a")
        cs.settle("a", 56)
        cs.reserve(user, 10, "参考图", ref="b")
        cs.settle("b", 35)
        cs.reserve(user, 106, "退回的", ref="c")
        cs.release("c")
        cs.grant(user, 100, "买卡", type_=cs.TYPE_PURCHASE)

        data = cs._read(user)
        total = sum(int(t["amount"]) for t in data["transactions"])
        assert total == cs.get_account()["balance"]
        assert cs.verify(user)["problems"] == []

    def test_每笔都记balance_after且能串成链(self, user):
        """回归：`balance_after` 曾经**从来没被写入过**，全是 0。

        它是事后定位"哪一笔开始错"的唯一线索，缺了就退化成只能看出总额不对。
        """
        cs.reserve(user, 70, "视频", ref="a")
        cs.settle("a", 56)
        cs.grant(user, 10, "补一点")
        ledger = list(reversed(cs.get_ledger()))     # 按时间正序
        running = 0
        for txn in ledger:
            running += txn["amount"]
            assert txn["balance_after"] == running, (
                f"第 {ledger.index(txn) + 1} 笔 balance_after 与累加不一致"
            )
            assert txn["balance_after"] >= 0

    def test_结算后派生值同步更新(self, user):
        """回归：结算后没重算派生值，导致"结算了但累计消耗还是 0"。

        结算流程会先追加退回流水、再改原流水状态；重算若只绑在追加那一步，
        后面那次状态变更就漏了。现已把重算绑在写入上。
        """
        cs.reserve(user, 70, "视频", ref="a")
        cs.settle("a", 56)
        a = cs.get_account()
        assert a["total_consumed"] == 56
        assert a["locked"] == 0

    def test_账本损坏时报错而不是清零(self, isolated_dir):
        """账本读不出来时必须报错。

        若降级成"空账本"，等于把用户的积分全抹掉——比报错严重得多。
        """
        cs.grant_signup_bonus(cs.LOCAL_USER)
        path = os.path.join(str(isolated_dir), f"{cs.LOCAL_USER}.json")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("{ 这不是 JSON")
        with pytest.raises(cs.CreditsError):
            cs.get_account()

    def test_账本格式异常时报错(self, isolated_dir):
        path = os.path.join(str(isolated_dir), f"{cs.LOCAL_USER}.json")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write('{"balance": 999, "transactions": {}}')
        with pytest.raises(cs.CreditsError):
            cs.get_account()


class TestConcurrency:
    def test_并发预扣不会超发(self):
        """10 个线程同时抢 300 积分，每个要 70。

        最多只应有 4 个成功（4×70=280 ≤ 300），且余额绝不为负。
        这条测试逼的是"读-改-写"必须有锁。
        """
        cs.grant(cs.LOCAL_USER, 300, "初始")
        ok, failed = [], []

        def worker(i):
            try:
                ok.append(cs.reserve(cs.LOCAL_USER, 70, f"并发 {i}", ref=f"c{i}"))
            except cs.InsufficientCredits:
                failed.append(i)

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        a = cs.get_account()
        assert len(ok) == 4, f"成功数应为 4，实际 {len(ok)}"
        assert a["balance"] == 300 - 4 * 70
        assert a["balance"] >= 0
        assert cs.verify(cs.LOCAL_USER)["problems"] == []
