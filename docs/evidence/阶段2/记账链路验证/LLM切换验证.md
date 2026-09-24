# 主用 LLM 切换为 DeepSeek V4.1 Flash（验证记录）

| 项目 | 内容 |
| --- | --- |
| 日期 | 2026-09-23 |
| 结论 | ✅ 已切换并实测通过 |
| 花费 | **约 ¥0.0013**（一次短问答） |
| 是否需要新 API Key | **不需要** |

## 核心发现：不需要申请新 Key

主用 LLM 从 `qwen-max`（通义）换成 **`deepseek-v4-1-flash-260910`**（火山方舟托管）。

**该模型已在现有方舟账号中可用**，用现有方舟 Key 直接调通（实测 HTTP 200）：

```bash
curl -X POST https://ark.cn-beijing.volces.com/api/v3/chat/completions \
  -H "Authorization: Bearer $ARK_API_KEY" \
  -d '{"model":"deepseek-v4-1-flash-260910","messages":[{"role":"user","content":"只回复两个字：可用"}]}'
```

所以**不用去 DeepSeek 官方平台申请 Key**。做法是把配置里 `deepseek` 槽位
指向方舟的 OpenAI 兼容接口——现有 DeepSeek 客户端走的就是 `openai` SDK，
`base_url` 可配，因此**零代码改动**即可复用：

```yaml
deepseek:
  api_key:  <方舟 Key>                                    # 注意：不是 DeepSeek 官方 Key
  base_url: https://ark.cn-beijing.volces.com/api/v3      # 方舟的兼容接口
models:
  llm: deepseek-v4-1-flash-260910
```

## 实测结果

```
回复 : 分镜是拍摄前用画面草图规划镜头与顺序。
记账 : 1 笔  ¥0.001224
       输入 52 tokens × 1.0 元/百万；输出 293 tokens × 4.0 元/百万
```

**与 qwen-max 的抽样对比**（同一问题）：

| 模型 | 费率（输入/输出，元/百万） | 本次成本 |
| --- | --- | ---: |
| qwen-max（原） | 2.4 / 9.6 | ¥0.00294 |
| **DeepSeek V4.1 Flash** | 1 / 4 | **¥0.00122** |

便宜约 **58%**。

## 三点需要注意的

### 1. 它是**推理模型**，输出 tokens 含 reasoning

上面那次 25 字的回答消耗了 **293 个输出 tokens**——大部分花在 reasoning 上，
而 reasoning 已计入 `completion_tokens`，所以按 `completion_tokens` 计费是对的，
**不要再额外加** `reasoning_tokens`。

副作用：`max_tokens` 给小了会被推理吃光、`content` 返回空。
现有客户端已有兜底（`DEFAULT_DEEPSEEK_MAX_TOKENS = 20000`，且识别
`finish_reason == "length"` 与 `reasoning_tokens` 并重试），无需改动。

**但重试是计费的**——所以 `report_chat_usage` 放在"确认 content 可用之前"调用，
否则重试那几次的钱会全部漏记。已有单测锁住这条。

### 2. VLM 没有一起换（仍是通义 `qwen3.7-plus`）

DeepSeek V4.1 Flash 的官方介绍称原生支持多模态视觉理解，
但**方舟把它暴露为纯文本**：

```
deepseek-v4-1-flash-260910  input_modalities: ['text']
```

所以图片评估环节还不能离开通义，**双平台结构暂时保留**。

> 若想做成单平台，方舟上有个候选：`doubao-seed-evolving`
> （`input_modalities: ['text','image','video']`，任务类型含
> `VisualQuestionAnswering`）。换它需要单独验证画质与成本，本次未做。

### 3. 文本成本需要重新实测

`pricing_calc.py` 里的「剧本生成 ¥0.72」是 **qwen-max 时代**跑出来的。
换了模型必须重测——不能靠上面那次短问答外推：推理模型的 reasoning 开销
在长短文上的占比不同。已记入待确认问题 Q6。

## 顺带修掉的两个隐患

### `llm_deepseek.py` 原先**不上报用量**

它读 `response.usage` 只是为了打日志。若不补，切到 DeepSeek 后
**文本成本会重新变成 0**——正是刚修完的那个坑。

已补上报，并把该客户端纳入"必须报用量"的静态单测名单（现为 6 个客户端）。

> 这也说明"换模型"有个容易漏的步骤：**换模型必须同时登记定价并确认用量上报**，
> 否则模型能跑通、回复也对，但账本里什么都记不下。
> 已加一条单测：读 `config.yaml` 的主用 LLM，断言它存在于定价注册表中。

### 配置默认值原来指向**本账号不存在的模型**

`config.py` 的 `DEFAULT_CONFIG` 里是上游模板值
（`qwen3.5-plus` / `doubao-seedream-5-0-260128` / `wan2.7-i2v`），
本项目账号并未开通这些。一旦 `config.yaml` 丢失而回退到默认值，
会静默调用不存在的模型。

已把默认值对齐**本项目实测可用**的那一组（DeepSeek + qwen3.7-plus +
seedream-4.0 + seedance-2.0）。

## 仍待核实（需要你在方舟控制台看一眼）

| 项 | 现状 | 影响 |
| --- | --- | --- |
| **DeepSeek V4.1 Flash 的方舟价目** | 注册表里填的是 **DeepSeek 官方平台闲时价**（缓存 0.02 / 未命中 1 / 输出 4），标 `verified=false` | 方舟是转售方、价目独立；且**峰谷价未建模**，高峰时段成本会被低估一半 |
| Seedance 2.5 单价 | 70 元/百万（单一二手来源） | 高端视频档（107 积分）可能虚高 |

两件事在方舟控制台「模型价格」页一次就能抄完。
