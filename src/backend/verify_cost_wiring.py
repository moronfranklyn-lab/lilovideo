#!/usr/bin/env python3
"""真实记账验证：跑一次**最便宜**的 Seedance 生成，确认成本真的落账。

为什么必须真跑一次
------------------
成本链路的失效方式是"静默"的：模块齐全、测试全绿、接口 200，
但一条记录都没有。上一轮开发就是这样——`record_usage()` 写好了却从未被调用，
真实项目的 `cost.json` 一个都不存在。

所以这条验证不能只看接口返回，必须**断言文件里出现了这笔钱**。

省钱设计
--------
1. 用已有参考图，不重新生成图片（省 ¥0.20）
2. 用 480P + Fast 档（最便宜的可用组合）
3. 只跑一个 5 秒片段，不跑完整流程
4. 全程走真实客户端代码路径（`SeedanceVideoClient`），不是直接请求 HTTP——
   要验证的正是"客户端有没有把 usage 交出来"

用法
    python3 verify_cost_wiring.py --dry-run    # 只打印将要做什么，不花钱
    python3 verify_cost_wiring.py              # 真跑一次
"""

from __future__ import annotations

import argparse
import json
import os
import sys

_BACKEND = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _BACKEND)

from config import Config  # noqa: E402
from models import cost_store  # noqa: E402
from models.cost_store import cost_scope  # noqa: E402
from models.video_seedance import SeedanceVideoClient  # noqa: E402

# 最便宜的档位组合：Fast 的费率最低（37 元/百万），480P 的 tokens 最少。
MODEL = "doubao-seedance-2-0-fast-260128"
RESOLUTION = "480p"
DURATION = 5
SESSION_ID = "verify_cost_wiring"

def make_synthetic_image(path: str) -> str:
    """本地生成一张抽象图，作为视频输入。

    为什么不用项目里的真实参考图：第一次真跑被平台**内容审核拒绝**了——

        InputImageSensitiveContentDetected.PrivacyInformation
        "the input image may contain real person"

    ARK 会拒绝含真人肖像的输入图。这本身是个值得记录的产品风险
    （用户上传的参考图可能被审核拦下，流程要能优雅失败），
    但用它做记账验证会让验证本身不稳定。

    所以这里用 Pillow 现画一张抽象图：不含真人、零成本、结果确定。
    视频内容长什么样不影响本次要验证的东西（钱有没有落账）。
    """
    from PIL import Image, ImageDraw

    os.makedirs(os.path.dirname(path), exist_ok=True)
    width, height = 640, 360
    img = Image.new("RGB", (width, height))
    draw = ImageDraw.Draw(img)

    # 竖直渐变 + 几个几何块，避免纯色导致模型输出退化
    for y in range(height):
        ratio = y / height
        draw.line(
            [(0, y), (width, y)],
            fill=(int(20 + 60 * ratio), int(30 + 90 * ratio), int(80 + 120 * ratio)),
        )
    draw.ellipse((80, 60, 320, 300), fill=(230, 150, 70))
    draw.rectangle((360, 90, 600, 270), fill=(60, 200, 180))
    img.save(path, "JPEG", quality=90)
    return path


def _run_generation(client, image: str, save_path: str, resolution: str) -> None:
    """调用真实客户端。失败时给出人能看懂的诊断，而不是抛栈。"""
    import requests

    prompt = "镜头缓慢推进，画面稳定，无字幕无水印。"
    try:
        # **必须包在计费作用域里** —— 这里模拟 orchestrator.execute_stage 的包法。
        # 作用域就是被测对象之一：它一漏，客户端报的用量就无处可去。
        with cost_scope(SESSION_ID, "video_generation"):
            client.generate_video(
                prompt=prompt,
                image_path=image,
                save_path=save_path,
                model=MODEL,
                duration=DURATION,
                ratio="16:9",
                resolution=resolution,
            )
    except requests.exceptions.HTTPError as exc:
        body = ""
        try:
            body = exc.response.text[:400]
        except Exception:  # noqa: BLE001
            pass
        raise SystemExit(
            f"\n❌ 提交被平台拒绝（HTTP {exc.response.status_code}），**未产生任何费用**。\n"
            f"   响应：{body}\n\n"
            "   常见原因：\n"
            "     · InputImageSensitiveContentDetected → 输入图含真人肖像，换一张图\n"
            "     · InvalidEndpointOrModel.NotFound    → 模型 ID 写错（用 GET /api/v3/models 查）\n"
        ) from exc


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="只打印计划，不调用 API")
    ap.add_argument("--resolution", default=RESOLUTION)
    ap.add_argument("--image", help="指定输入图；默认本地生成一张抽象图（零成本、不含真人）")
    args = ap.parse_args(argv[1:])

    if args.image:
        image = os.path.abspath(args.image)
        if not os.path.exists(image):
            raise SystemExit(f"指定的图片不存在：{image}")
    else:
        image = make_synthetic_image(
            os.path.join(Config.RESULT_DIR, "verify", "cost_wiring_input.jpg")
        )

    save_path = os.path.join(Config.RESULT_DIR, "video", "verify_cost_wiring.mp4")

    print("=" * 68)
    print("真实记账验证")
    print("=" * 68)
    print(f"  模型      {MODEL}")
    print(f"  分辨率    {args.resolution}")
    print(f"  时长      {DURATION} 秒")
    print(f"  输入图    {os.path.relpath(image, Config.BASE_DIR)}（本地生成，不计费）")
    print(f"  会话      {SESSION_ID}")
    print(f"  预计花费  ¥1.8 ~ ¥4.0（取决于平台是否接受 480p）")
    print()

    # 已存在的记录先看一眼——**dry-run 绝不能清账**。
    #
    # 这里踩过一次：`clear()` 原先写在 dry-run 判断之前，
    # 结果"只是看看计划"的那次运行把上一次真跑留下的证据删了。
    # 只读模式必须是只读的，这跟"确认前不删数据"是同一条原则。
    existing = cost_store.get_summary(SESSION_ID)
    if existing["call_count"]:
        print(f"  已有记录  {existing['call_count']} 笔 / ¥{existing['total']:.4f}"
              f"（真跑时会先清空重记）")
        print()

    if args.dry_run:
        print("dry-run：不调用 API、不花钱、**不动任何已有记录**。")
        print("        去掉 --dry-run 才真跑（届时会清空该会话的旧记录重记）。")
        return 0

    cost_store.clear(SESSION_ID)

    _run_generation(SeedanceVideoClient(), image, save_path, args.resolution)

    # ── 关键断言：钱必须落进文件 ──────────────────────────────────────
    summary = cost_store.get_summary(SESSION_ID)
    print()
    print("-" * 68)
    print("记账结果")
    print("-" * 68)
    print(json.dumps(summary, ensure_ascii=False, indent=2)[:1200])
    print()

    path = os.path.join(cost_store.SESSIONS_DIR, f"{SESSION_ID}.cost.json")
    failures = []
    if summary["call_count"] != 1:
        failures.append(f"记录笔数应为 1，实际 {summary['call_count']}")
    if summary["total"] <= 0:
        failures.append(f"金额应为正数，实际 {summary['total']}")
    if not os.path.exists(path):
        failures.append(f"成本文件不存在：{path}")
    if summary["records"]:
        rec = summary["records"][0]
        tokens = rec.get("usage", {}).get("output_tokens", 0)
        if not tokens:
            failures.append("记录里没有 output_tokens——usage 没被取到")

    print(f"成本文件：{os.path.relpath(path, Config.BASE_DIR)}")
    if failures:
        print()
        print("❌ 记账链路仍有问题：")
        for item in failures:
            print(f"   · {item}")
        return 1

    rec = summary["records"][0]
    tokens = rec["usage"]["output_tokens"]
    print()
    print(f"✅ 成本已落账：{tokens:,} tokens → ¥{summary['total']:.4f}")
    print(f"   折算 {tokens / DURATION:,.0f} tokens/秒（{args.resolution}, {DURATION} 秒）")
    print(f"   明细：{rec['breakdown']}")
    print()
    print("把这个 tokens/秒 与 pricing.SEEDANCE_EFFECTIVE_PIXELS 的推算对比：")
    from models.pricing import seedance_tokens
    for res in ("480P", "720P", "1080P"):
        est = seedance_tokens(DURATION, res)
        mark = "  ← 本次实测" if res.lower() == args.resolution.lower() else ""
        print(f"   {res:6} 推算 {est:>9,} tokens{mark}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
