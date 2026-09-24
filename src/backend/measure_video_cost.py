"""实测对比不同视频模型的实际 token 消耗与成本。

为什么必须实测
--------------
官方定价是元/百万 tokens，但**每个模型生成一秒视频消耗多少 tokens 是未知的**。
这个数字只能从真实调用的响应体里取。

此前已用这个方法纠正过一次错误：文档曾写 5 秒片段 ¥7.10，实测发现是
108900 tokens 即 ¥5.01，差 29%。

用法
    python3 measure_video_cost.py            # 测全部候选
    python3 measure_video_cost.py --only fast
"""

from __future__ import annotations

import argparse
import json
import sys
import time

import requests
import yaml

# 候选模型（按名称过滤用）
CANDIDATES = [
    ("标准", "doubao-seedance-2-0-260128", "doubao-seedance-2-0-260128"),
    ("fast", "doubao-seedance-2-0-fast-260128", "doubao-seedance-2-0-fast-260128"),
    ("mini", "doubao-seedance-2-0-mini-t2v", "doubao-seedance-2-0-mini-t2v"),
]

BASE = "https://ark.cn-beijing.volces.com/api/v3"
# 方舟公布的每百万 tokens 单价（元）。取「不含视频输入」档，因为首帧生视频
# 只传入一张参考图，不构成视频输入。
RATE_NO_VIDEO = 46.0
RATE_WITH_VIDEO = 28.0


def load_key() -> str:
    cfg = yaml.safe_load(open("config.yaml", encoding="utf-8"))
    return str(cfg["api_providers"]["ark"]["api_key"])


def submit(key: str, model: str, seconds: int = 5, ratio: str = "16:9") -> str | None:
    """提交一个最简文本生视频任务，返回 task_id。"""
    r = requests.post(
        f"{BASE}/contents/generations/tasks",
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        json={
            "model": model,
            "content": [{
                "type": "text",
                "text": f"A calm ocean wave at sunset, cinematic --duration {seconds} --ratio {ratio}",
            }],
        },
        timeout=60,
    )
    if r.status_code != 200:
        print(f"    提交失败 HTTP {r.status_code}: {r.text[:200]}")
        return None
    d = r.json()
    return d.get("id") or d.get("task_id")


def poll(key: str, task_id: str, max_wait: int = 600) -> dict | None:
    """轮询到完成，返回完整响应体。"""
    start = time.time()
    last = ""
    while time.time() - start < max_wait:
        time.sleep(15)
        try:
            r = requests.get(
                f"{BASE}/contents/generations/tasks/{task_id}",
                headers={"Authorization": f"Bearer {key}"}, timeout=30)
            d = r.json()
        except Exception as e:
            print(f"    轮询异常 {type(e).__name__}")
            continue
        st = d.get("status", "?")
        if st != last:
            print(f"    [{int(time.time()-start):>3}s] {st}")
            last = st
        if st in ("succeeded", "failed", "expired"):
            return d
    print("    超时")
    return None


def measure(key: str, label: str, model: str, seconds: int) -> dict | None:
    print(f"\n=== {label} · {model} ===")
    tid = submit(key, model, seconds)
    if not tid:
        return None
    print(f"  任务 {tid}")
    d = poll(key, tid)
    if not d or d.get("status") != "succeeded":
        print(f"  未成功: {d.get('status') if d else '无响应'}")
        if d and d.get("error"):
            print(f"  错误: {str(d['error'])[:200]}")
        return None

    usage = d.get("usage") or {}
    toks = usage.get("total_tokens") or usage.get("completion_tokens") or 0
    dur = d.get("duration") or seconds
    res = d.get("resolution", "?")

    if not toks:
        print("  响应中无 usage，无法计算成本")
        return None

    c46 = toks / 1_000_000 * RATE_NO_VIDEO
    c28 = toks / 1_000_000 * RATE_WITH_VIDEO
    print(f"  ✓ 成功  duration={dur}s resolution={res}")
    print(f"    tokens = {toks:,}  →  {toks/dur:,.0f} tokens/秒")
    print(f"    成本(46元档) = ¥{c46:.2f}  即 ¥{c46/dur:.2f}/秒")
    print(f"    成本(28元档) = ¥{c28:.2f}  即 ¥{c28/dur:.2f}/秒")
    return {"label": label, "model": model, "tokens": toks, "seconds": dur,
            "tokens_per_sec": toks / dur, "cost46": c46, "cost28": c28,
            "resolution": res}


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", help="只测名称包含该字符串的候选")
    ap.add_argument("--seconds", type=int, default=5)
    args = ap.parse_args(argv[1:])

    key = load_key()
    cands = [c for c in CANDIDATES if not args.only or args.only in c[0]]

    print(f"将实测 {len(cands)} 个模型，每个 {args.seconds} 秒")
    print("注意：每个都会真实计费。5 秒片段按标准版估算约 ¥5。")

    results = []
    for label, display, model in cands:
        r = measure(key, label, model, args.seconds)
        if r:
            results.append(r)

    if results:
        print("\n" + "=" * 68)
        print("汇总")
        print("=" * 68)
        print(f"{'模型':<10}{'tokens/秒':>12}{'¥/秒':>10}{'5秒成本':>12}{'相对标准版':>14}")
        base = next((r for r in results if r["label"] == "标准"), None)
        for r in results:
            ratio = f"{r['tokens_per_sec']/base['tokens_per_sec']:.0%}" if base else "—"
            print(f"{r['label']:<10}{r['tokens_per_sec']:>12,.0f}{r['cost46']/r['seconds']:>10.2f}"
                  f"{r['cost46']:>12.2f}{ratio:>14}")
    else:
        print("\n未取得任何有效测量")

    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
