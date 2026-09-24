"""模型定价注册表。

成本核算的地基。每个价格都带来源与核实状态，**不允许估算值冒充真实价格**。

设计原则
--------
1. 价格是外部事实，会变。因此本文件只存"当前已知值 + 来源 + 核实日期"，
   计算逻辑不硬编码价格。
2. 未核实的条目显式标 `verified=False` 并写明原因，调用方能据此提示用户
   "该模型成本不可靠"，而不是默默算出一个错的数。
3. 找不到定价的模型返回 None，由调用方决定如何处理（本项目选择跳过而非估算）。

计费方式（`billing`）
-------------------
- ``per_token``：按 tokens 计费，需要 input_tokens / output_tokens
- ``per_second``：按视频秒数计费
- ``per_image``：按生成张数计费

单位统一为**人民币元**。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass(frozen=True)
class PriceSpec:
    """一个模型的定价规格。"""

    model_id: str
    provider: str
    billing: str  # per_token | per_second | per_image
    # 按 tokens 计费时使用（单位：元 / 百万 tokens）
    input_per_million: Optional[float] = None
    output_per_million: Optional[float] = None
    cached_input_per_million: Optional[float] = None
    # 按秒 / 张计费时使用（单位：元）
    per_second: Optional[float] = None
    per_image: Optional[float] = None
    # 同一模型的全部档位价格，形如 (("720P 无声", 0.15), ("1080P 无声", 0.25))。
    #
    # 为什么要单独存：视频模型的"每秒多少钱"取决于分辨率和是否带音轨，
    # 一个模型往往有 2–4 个价。若只把最便宜那档放进 `per_second`、
    # 其余写进 `note` 的自由文本里，程序就永远读不到它们——
    # 积分换算表只能靠人手抄一遍，抄错的风险立刻回来。
    #
    # 约定：`per_second` 存"默认档"，且当 variants 非空时，
    # `per_second` 必须等于 variants 中的某一档（由单测保证）。
    variants: tuple[tuple[str, float], ...] = ()
    # per_token **视频**模型的类型标记，值是 720P 每秒的 tokens 用量。
    #
    # 它主要用来回答"这个 per_token 模型是不是视频模型"——LLM 与视频模型都按
    # tokens 计费，但只有视频模型能按公式把秒数折成 tokens。
    # **真实推算一律走 `seedance_tokens()`**，不要拿这个字段做算术。
    tokens_per_second_720p: Optional[float] = None
    # per_token 视频模型的**分分辨率费率**（元/百万 tokens，不含视频输入）。
    #
    # 为什么费率也要分档：Seedance 2.5 的 1080P 是 **77**，而 480P/720P 是 70。
    # 若只存一个费率，1080P 会被按 70 报价，少收 9%。
    #
    # 约定：**为空表示"各分辨率费率未知，不要报价"**，而不是"各分辨率同价"。
    # 这条约定是刻意的：宁可不报价，也别拿 720P 的费率去充 1080P。
    token_rate_variants: tuple[tuple[str, float], ...] = ()
    # 含视频输入（视频编辑 / 视频延长）时的费率，同样分分辨率。
    # 注意这类任务按 (输入+输出) 总时长计费，所以单价更低却往往总价更高。
    token_rate_variants_with_input: tuple[tuple[str, float], ...] = ()
    unit_label: str = ""
    verified: bool = False
    source: str = ""
    note: str = ""

    def resolve_token_rate(
        self, resolution: Optional[str] = None, with_video_input: bool = False
    ) -> Optional[float]:
        """挑出该分辨率的 token 费率（元/百万 tokens）。

        返回 None 有两种含义，调用方都要当成"不能报价"处理：

        - 该模型没有分分辨率费率，且调用方没有指定分辨率 → 用默认费率
          （调用方自行退回 `output_per_million`）
        - **指定了分辨率但费率表里没有** → 明确报未知，不要退默认
        """
        table = (
            self.token_rate_variants_with_input
            if with_video_input
            else self.token_rate_variants
        )
        if not table:
            return None
        if resolution is None:
            return None
        want = resolution.strip().upper()
        for label, rate in table:
            if label.split()[0].upper() == want:
                return rate
        return None

    def resolve(
        self, resolution: Optional[str] = None, audio: Optional[bool] = None
    ) -> Optional[tuple[str, float]]:
        """按分辨率和音轨挑出具体档位，返回 `(档位名, 每秒元)`。

        返回 None 有两种情况，调用方要区分对待：

        - 该模型没有分档（``variants`` 为空）→ 调用方应退回 ``per_second`` 默认档
        - **明确指定了档位但该档不存在** → 调用方应报"成本未知"，
          绝不能悄悄按默认档算——那会把 1080P 记成 720P 的价，
          少记 40%~67% 而不报错。

        客户端只报"我请求了什么"（分辨率、要不要音轨），
        由这里决定"这对应哪一档"。定价解释权留在定价层。
        """
        if not self.variants:
            return None
        if resolution is None and audio is None:
            return None

        want = (resolution or "").strip().upper()
        candidates = [
            (name, price) for name, price in self.variants
            if not want or name.split()[0].upper() == want
        ]
        if not candidates:
            return None

        if audio is not None and len(candidates) > 1:
            marker = "带音" if audio else "无声"
            with_marker = [c for c in candidates if marker in c[0]]
            # 该模型没有音轨分档时（如"720P" vs "1080P"），marker 一个都不匹配，
            # 此时视为该模型不区分音轨，接受全部候选。
            if with_marker:
                candidates = with_marker

        return candidates[0]


# ── Seedance 的计费口径（以方舟控制台价目页为准）────────────────────────
#
# 官方公式（控制台价目页原文）：
#
#     不含视频输入：Token用量 = (输出宽 × 输出高 × 输出帧率 × 输出时长) / 1024
#     包含视频输入：Token用量 = (输出宽 × 输出高 × 输出帧率 × (输入+输出时长)) / 1024
#
# 分辨率与帧率由价目页的 6 行示例**反推确认**（三档 × 两种时长）：
#
#     480P  854 × 480     5 秒 → 48,037.5 tokens   20 秒 → 192,150
#     720P  1280 × 720    5 秒 → 108,000  tokens   20 秒 → 432,000
#     1080P 1920 × 1080   5 秒 → 243,000  tokens   20 秒 → 972,000
#
# 六行全部与公式精确吻合，所以这不是猜的。
#
# ## 曾经在这里犯过一个错，记下来
#
# 在拿到官方价目页之前，本文件曾按**单次实测**反推出"480P 的有效像素是
# 864 × 496（而不是名义的 864 × 480）"，还写了注释和单测把它锁死。
# 官方价目页出来后证明**那是错的**：480P 就是 854 × 480，
# 官方公式干净利落，六行示例全部吻合。
#
# 教训：**单次测量可以证伪，但不能单独用来建模。**
# 一个样本能精确命中多种解释（864 × 496 × 121 帧也能算出 50,638），
# 精确吻合不等于解释正确。有官方口径时以官方为准，实测用来交叉验证。
#
# ## 实测与官方的偏差（如实记录，未解释）
#
#     720P 5 秒   实测 108,900  vs 官方 108,000    实测偏高 +0.83%
#     480P 5 秒   实测  50,638  vs 官方  48,037.5  实测偏高 +5.41%
#
# 方向是"实际计费略高于价目页示例"。720P 的偏差在千分位，报价取整后无影响；
# 480P 偏差 5% 但该档当前不进产品菜单。**若要把 480P 上架，需先重测一次。**
#
# 注意：成本记账走的是 API 返回的真实 `usage.completion_tokens`，
# 不受本公式影响；本公式只用于**生成前报价**与**产品定价**。
SEEDANCE_FRAME_RATE = 24

# 720P 每秒用量（官方公式：1280 × 720 × 24 ÷ 1024 = 21,600）。
# 早先这里是 21780——那是把实测偏差误读成「+1 帧」后的产物，已更正。
SEEDANCE_TOKENS_PER_SECOND_720P = 1280 * 720 * SEEDANCE_FRAME_RATE / 1024

SEEDANCE_RESOLUTION_PIXELS: dict[str, tuple[int, int]] = {
    "480P": (854, 480),
    "720P": (1280, 720),
    "1080P": (1920, 1080),
}


def seedance_seconds_billed(
    output_seconds: float, input_seconds: float = 0.0
) -> float:
    """计费时长。

    "含视频输入"的任务（视频编辑 / 视频延长）按 **输入+输出** 总时长计费，
    这也是为什么它的单价更低（42 vs 70）却往往更贵——
    10 秒输入 + 10 秒输出会按 20 秒算，是普通 5 秒生成的 4 倍用量。
    """
    return max(output_seconds, 0.0) + max(input_seconds, 0.0)


def seedance_tokens(
    seconds: float,
    resolution: str = "720P",
    input_seconds: float = 0.0,
) -> Optional[float]:
    """按官方公式推算 Seedance 一次生成产生的 output tokens。

    公式：``宽 × 高 × 帧率 × 计费时长 ÷ 1024``。

    返回 float（官方示例里就有 48,037.5 这种小数）；分辨率未登记时返回 **None**。
    """
    pixels = SEEDANCE_RESOLUTION_PIXELS.get(resolution)
    if not pixels or seconds <= 0:
        return None
    width, height = pixels
    billed = seedance_seconds_billed(seconds, input_seconds)
    return width * height * SEEDANCE_FRAME_RATE * billed / 1024


# ── 注册表 ─────────────────────────────────────────────────────────────
#
# 核实日期：2026-09-22。价格来源为各平台官方文档，见 source 字段。
# 修改价格时请同时更新 note 里的核实日期。
#
PRICING: dict[str, PriceSpec] = {
    # ── 视频：火山方舟 Seedance ────────────────────────────────────────
    "doubao-seedance-2-0-260128": PriceSpec(
        model_id="doubao-seedance-2-0-260128",
        provider="ark",
        billing="per_token",
        output_per_million=46.0,
        # 只取到 720P 的费率；480P / 1080P **未取到**，故不登记（宁可不报价）
        token_rate_variants=(("720P", 46.0),),
        token_rate_variants_with_input=(("720P", 28.0),),
        tokens_per_second_720p=SEEDANCE_TOKENS_PER_SECOND_720P,
        verified=True,
        source="https://www.donews.com/news/detail/4/6510676.html",
        note=(
            "火山引擎官方公布：不含视频输入 46 元/百万 tokens，含视频输入 28 元/百万 tokens。"
            "本条目取 46 元档，因为主流程首帧生视频只传入一张参考图，不与既有视频做输入合成。"
            "**用量已实测取证**：查询真实完成任务得到 "
            "usage.completion_tokens = 108900（5 秒 / 720p / 24fps），"
            "官方公式给 108,000 tokens（21,600 tokens/秒），按 46 元档折合 ¥0.99/秒，"
            "与官方口径「约 1 元/秒」一致。实测为 108,900（+0.83%，见文件顶部说明）。"
            "核实日期 2026-09-22。"
        ),
    ),
    "doubao-seedance-2-0-fast-260128": PriceSpec(
        model_id="doubao-seedance-2-0-fast-260128",
        provider="ark",
        billing="per_token",
        output_per_million=37.0,
        # 只取到 720P 的费率；480P / 1080P **未取到**，故不登记（宁可不报价）
        token_rate_variants=(("720P", 37.0),),
        tokens_per_second_720p=SEEDANCE_TOKENS_PER_SECOND_720P,
        verified=True,
        source="https://crazyrouter.com/zh/blog/seedance-2-0-actual-output-token-billing-explained",
        note=(
            "Fast 版费率 37 元/百万 tokens（不含视频输入），低于标准版的 46 元。"
            "来源为该文引用的方舟计费键 `doubao-seedance-2-0-fast:video0`。"
            "注意：单价更低不等于总价更低——tokens/秒 由任务类型决定，"
            "含视频输入的任务 tokens 量约为文生视频的 2 倍。核实日期 2026-09-22。"
        ),
    ),
    "doubao-seedance-2-0-mini-260615": PriceSpec(
        model_id="doubao-seedance-2-0-mini-260615",
        provider="ark",
        billing="per_token",
        output_per_million=23.0,
        # 只取到 720P 的费率；480P / 1080P **未取到**，故不登记（宁可不报价）
        token_rate_variants=(("720P", 23.0),),
        token_rate_variants_with_input=(("720P", 14.0),),
        tokens_per_second_720p=SEEDANCE_TOKENS_PER_SECOND_720P,
        verified=True,
        source="https://m.ithome.com/html/964672.htm",
        note=(
            "火山引擎 2026-06-15 上线、官方公布定价：图生视频 0.023 元/千 tokens"
            "（= 23 元/百万），视频生视频 0.014 元/千（= 14 元/百万）。本条目取图生视频档。"
            "**交叉验证**：23 元/百万 × 21,600 tokens/秒 = ¥0.50/秒，"
            "与官方口径「720P 单秒约 0.5 元、较标准版降低约一半」逐字吻合；"
            "且 23 ≈ 46/2，与「定价腰斩」的媒体报道自洽。"
            "IT之家与全天候科技两篇独立报道引用同一组官方数字，故记为已核实。"
            "核实日期 2026-09-23。"
        ),
    ),
    "doubao-seedance-2-5-260628": PriceSpec(
        model_id="doubao-seedance-2-5-260628",
        provider="ark",
        billing="per_token",
        output_per_million=70.0,
        tokens_per_second_720p=SEEDANCE_TOKENS_PER_SECOND_720P,
        # 三档费率来自**方舟控制台价目页**（产品负责人截图核对，2026-09-23）：
        #   不含视频输入 480P/720P = 70 元/百万，1080P = 77
        #   含视频输入   480P/720P = 42 元/百万，1080P = 46
        # 1080P 的费率**比 480P/720P 高 10%**，所以费率必须分档登记。
        token_rate_variants=(("480P", 70.0), ("720P", 70.0), ("1080P", 77.0)),
        token_rate_variants_with_input=(
            ("480P", 42.0), ("720P", 42.0), ("1080P", 46.0)
        ),
        verified=True,
        source="方舟控制台价目页（产品负责人截图核对，2026-09-23）",
        note=(
            "Seedance 2.5，2026-07-31 上线。费率已由方舟控制台价目页核实。"
            "**该页同时给出了官方计费公式**，本文件的 tokens 推算已按它改写："
            "`tokens = 宽 × 高 × 帧率 × 计费时长 ÷ 1024`，帧率 24，"
            "分辨率 480P=854×480 / 720P=1280×720 / 1080P=1920×1080。"
            "价目页 6 行示例（3 档 × 5 秒/20 秒）全部与公式吻合。"
            "**注意「含视频输入」按 (输入+输出) 总时长计费**，"
            "所以单价更低（42 vs 70）却常常更贵：10 秒输入 + 10 秒输出按 20 秒算。"
            "核实日期 2026-09-23。"
        ),
    ),
    # ── 视频：阿里云百炼（按秒计费，成本可预测）─────────────────────────
    #
    # 与 Seedance 的 per-token 不同，通义视频模型按秒定价。这一点对产品很重要：
    # per-token 的实际用量随任务类型浮动（同一模型可差 2 倍），
    # per-second 则完全确定，适合作为"成本可预测"的选项提供给用户。
    #
    # 以下单价全部为**华北2（北京）区域官方原价**，逐条直读官方模型页取得
    # （核实日期 2026-09-23）。海外区域另有价格，本项目不部署海外，故不登记。
    "wan2.6-i2v-flash": PriceSpec(
        model_id="wan2.6-i2v-flash",
        provider="dashscope",
        billing="per_second",
        per_second=0.15,
        variants=(
            ("720P 无声", 0.15),
            ("720P 带音", 0.30),
            ("1080P 无声", 0.25),
            ("1080P 带音", 0.50),
        ),
        unit_label="720P 无声",
        verified=True,
        source="https://help.aliyun.com/zh/model-studio/wan2-6-i2v-flash",
        note=(
            "全表最便宜的一档，也是样片模式的默认档。"
            "支持最高 15 秒、多镜头叙事、多人对话。"
            "注意 1080P 无声（0.25）比 720P 带音（0.30）还便宜——"
            "分辨率和音轨是两个独立加价项，不要假设 1080P 一定更贵。核实日期 2026-09-23。"
        ),
    ),
    "wan2.6-i2v": PriceSpec(
        model_id="wan2.6-i2v",
        provider="dashscope",
        billing="per_second",
        per_second=0.6,
        variants=(("720P", 0.6), ("1080P", 1.0)),
        unit_label="720P",
        verified=True,
        source="https://help.aliyun.com/zh/model-studio/wan2-6-i2v",
        note=(
            "万相 2.6 图生视频标准档。官方页只给两个价（720P 0.6 / 1080P 1.0），"
            "没有像 flash 那样按音轨再分档。1080P 1.0 元/秒与 Seedance 2.0 同价，"
            "但通义是确定成本、Seedance 是浮动成本。核实日期 2026-09-23。"
        ),
    ),
    "wan2.7-i2v": PriceSpec(
        model_id="wan2.7-i2v",
        provider="dashscope",
        billing="per_second",
        per_second=0.6,
        variants=(("720P", 0.6), ("1080P", 1.0)),
        unit_label="720P",
        verified=True,
        source="https://help.aliyun.com/zh/model-studio/wan2-7-i2v",
        note=(
            "主打表演能力（文戏情感、动作戏），通义系里面向成片交付的档位。"
            "与 wan2.6-i2v 同价，是它在产品里的直接替代者。"
            "**这也是目前唯一已核实的 1080P 方案**（1.0 元/秒）。核实日期 2026-09-23。"
        ),
    ),
    "wan2.6-r2v": PriceSpec(
        model_id="wan2.6-r2v",
        provider="dashscope",
        billing="per_second",
        per_second=0.6,
        variants=(("720P", 0.6), ("1080P", 1.0)),
        unit_label="720P",
        verified=True,
        source="https://help.aliyun.com/zh/model-studio/wan2-6-r2v",
        note=(
            "参考生视频（r2v）：可指定人物或任意物品做参考，保持形象与声音一致，"
            "支持多角色参考合拍。**这是本项目「角色一致性」需求最对口的一档**，"
            "比 Seedance 便宜 40% 且成本确定。"
            "注意：用视频做参考时，输入视频时长也计入费用。核实日期 2026-09-23。"
        ),
    ),
    "wan2.6-r2v-flash": PriceSpec(
        model_id="wan2.6-r2v-flash",
        provider="dashscope",
        billing="per_second",
        per_second=0.15,
        variants=(
            ("720P 无声", 0.15),
            ("720P 带音", 0.30),
            ("1080P 无声", 0.25),
            ("1080P 带音", 0.50),
        ),
        unit_label="720P 无声",
        verified=True,
        source="https://help.aliyun.com/zh/model-studio/wan2-6-r2v-flash",
        note=(
            "r2v 的 Flash 档，价格与 wan2.6-i2v-flash 完全相同，但保留了参考能力。"
            "**产品含义**：想要角色一致性的用户不必为它付溢价，"
            "特价档可以直接给 r2v 而不是 i2v。核实日期 2026-09-23。"
        ),
    ),
    "wan2.7-r2v": PriceSpec(
        model_id="wan2.7-r2v",
        provider="dashscope",
        billing="per_second",
        per_second=0.6,
        variants=(("720P", 0.6), ("1080P", 1.0)),
        unit_label="720P",
        verified=True,
        source="https://help.aliyun.com/zh/model-studio/wan2-7-r2v",
        note=(
            "2.7 代参考生视频：最大 5 个图/视频混合参考，支持音频音色参考。"
            "与 wan2.6-r2v 同价。核实日期 2026-09-23。"
        ),
    ),
    "wan2.6-t2v": PriceSpec(
        model_id="wan2.6-t2v",
        provider="dashscope",
        billing="per_second",
        per_second=0.6,
        variants=(("720P", 0.6), ("1080P", 1.0)),
        unit_label="720P",
        verified=True,
        source="https://help.aliyun.com/zh/model-studio/wan2-6-t2v",
        note=(
            "文生视频，输出含音轨（输出模态 Video + Audio），价格未因带音而加价。"
            "最高 15 秒。本产品主流程是「参考图 → 视频」，t2v 只在用户没提供参考图时用到。"
            "核实日期 2026-09-23。"
        ),
    ),
    "wan2.7-t2v": PriceSpec(
        model_id="wan2.7-t2v",
        provider="dashscope",
        billing="per_second",
        per_second=0.6,
        variants=(("720P", 0.6), ("1080P", 1.0)),
        unit_label="720P",
        verified=True,
        source="https://help.aliyun.com/zh/model-studio/wan2-7-t2v",
        note="2.7 代文生视频，与 wan2.6-t2v 同价。核实日期 2026-09-23。",
    ),
    "happyhorse-1.0-i2v": PriceSpec(
        model_id="happyhorse-1.0-i2v",
        provider="dashscope",
        billing="per_second",
        per_second=0.9,
        variants=(("720P", 0.9), ("1080P", 1.6)),
        unit_label="720P",
        verified=True,
        source="https://help.aliyun.com/zh/model-studio/happyhorse-1-0-i2v",
        note=(
            "阿里 HappyHorse 图生视频。720P 0.9 元/秒比 Seedance 2.0 的 1.0 略便宜，"
            "但 1080P 1.6 元/秒是**全表最贵的档位**。"
            "灰测期曾有 720P 低至 0.44 元/秒的促销口径，那是活动价，不是原价，不登记。"
            "核实日期 2026-09-23。"
        ),
    ),
    "happyhorse-1.1-i2v": PriceSpec(
        model_id="happyhorse-1.1-i2v",
        provider="dashscope",
        billing="per_second",
        per_second=0.9,
        variants=(("480P", 0.45), ("720P", 0.9), ("1080P", 1.2)),
        unit_label="720P",
        verified=True,
        source="https://help.aliyun.com/zh/model-studio/happyhorse-1-1-i2v",
        note=(
            "1.1 代：画面质感、跨片段 ID 保持、音画同步改善。"
            "**值得注意的是它的 1080P（1.2）比 1.0 代的 1080P（1.6）更便宜**——"
            "新一代反而降价，说明 1.0 的 1080P 定价是历史包袱。"
            "480P 0.45 元/秒是通义侧唯一的 480P 档。核实日期 2026-09-23。"
        ),
    ),
    # ── 图片：火山方舟 Seedream（按张计费）──────────────────────────────
    "doubao-seedream-4-0-250828": PriceSpec(
        model_id="doubao-seedream-4-0-250828",
        provider="ark",
        billing="per_image",
        per_image=0.20,
        unit_label="每张",
        verified=True,
        source="https://www.modellix.ai/blog/seedream-4-0-price/",
        note=(
            "BytePlus 官方页（Seedream 4.0）标价 **$0.03/张，1K–4K 同价，"
            "生成失败不计费**。"
            "本条目取 ¥0.20/张：这是本项目真实预跑实测的单张成本，"
            "与 $0.03（约 ¥0.21）相差 5% 以内，两个独立来源互相印证，故记为已核实。"
            "**注意国内方舟的 CNY 价目页未直读**（前端渲染抓不到表格），"
            "若要精确到分，请在方舟控制台核对。"
            "另：该模型单次请求可批量出图（最多 15 张），每张独立计费，"
            "所以计费单位是**张**而不是**次**——客户端必须按返回的图片张数记账。"
            "核实日期 2026-09-23。"
        ),
    ),
    # ── 语言：火山方舟托管的 DeepSeek（本项目主用 LLM）──────────────────
    "deepseek-v4-1-flash-260910": PriceSpec(
        model_id="deepseek-v4-1-flash-260910",
        provider="ark",
        billing="per_token",
        input_per_million=1.0,
        output_per_million=4.0,
        # 方舟控制台价目页**只给了输入与输出两项**，没有缓存命中价。
        # 所以这里**不登记缓存价**——登记一个没核到的数（比如 DeepSeek 官方的 0.02）
        # 会让缓存命中被按 50 分之一的价计费，而那是没有依据的。
        # 未登记时 `_cost_per_token` 会退回按普通输入价计费（只会多算不会少算）。
        # 若日后确认方舟确有缓存价，再补这一项。
        cached_input_per_million=None,
        verified=True,
        source="方舟控制台「模型价格」页（产品负责人截图核对，2026-09-23）",
        note=(
            "本项目主用 LLM。方舟控制台价目页：**推理输入 1、推理输出 4 元/百万 tokens**，"
            "页面标注「空闲时段」为当前时段。核实日期 2026-09-23。\n"
            "仍有两处需要留意：\n"
            "1. **峰谷价没有建模**。页面出现「空闲时段」字样，说明可能存在高峰时段"
            "（DeepSeek 官方口径是高峰翻倍），而本注册表没有「时段」概念。"
            "若方舟确实分时段，高峰时段的成本会被低估。\n"
            "2. 该模型 2026-09-10 调过价，价格本身在变。\n"
            "**成本记账走 API 返回的真实用量，受影响的只是事前报价。**"
        ),
    ),
    # ── 语言与视觉：阿里云百炼 ─────────────────────────────────────────
    "qwen-max": PriceSpec(
        model_id="qwen-max",
        provider="dashscope",
        billing="per_token",
        input_per_million=2.4,
        output_per_million=9.6,
        cached_input_per_million=0.48,
        verified=True,
        source="https://help.aliyun.com/zh/model-studio/qwen-max",
        note="华北2（北京）区域原价：输入 2.4、输出 9.6、缓存命中 0.48 元/百万 tokens。核实日期 2026-09-22。",
    ),
    "qwen3.7-plus": PriceSpec(        model_id="qwen3.7-plus",
        provider="dashscope",
        billing="per_token",
        input_per_million=2.0,
        output_per_million=8.0,
        cached_input_per_million=0.4,
        verified=True,
        source="https://help.aliyun.com/zh/model-studio/qwen3-7-plus",
        note=(
            "华北2（北京）区域，输入 ≤256k 档：输入 2.0、输出 8.0、缓存命中 0.4 元/百万 tokens。"
            "输入超过 256k 时价格上升（6.0 / 24.0），本项目单次调用不会达到该量级，故只登记低价档。"
            "核实日期 2026-09-22。"
        ),
    ),
}


def get_price(model_id: str) -> Optional[PriceSpec]:
    """按模型 ID 取定价。未登记时返回 None（调用方应跳过而非估算）。"""
    if not model_id:
        return None
    return PRICING.get(str(model_id).strip())


def list_prices(provider: Optional[str] = None) -> list[PriceSpec]:
    """列出定价条目，可按平台过滤。"""
    items = list(PRICING.values())
    if provider:
        items = [p for p in items if p.provider == provider]
    return sorted(items, key=lambda p: (p.provider, p.model_id))


def unverified_models() -> list[str]:
    """列出定价未核实的模型 ID。用于在界面上提示成本不可靠。"""
    return sorted(m for m, p in PRICING.items() if not p.verified)
