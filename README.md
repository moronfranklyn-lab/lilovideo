<div align="center">

# Lilovideo

**从一句创意到一部成片**

一个 AI 视频生产系统：把「一句话」拆成一条可控的生产流水线，
在关键节点停下来让你确认，最后交付完整成片。

[![Python](https://img.shields.io/badge/Python-3.10%2B-3776AB.svg)](https://www.python.org/downloads/)
[![Node.js](https://img.shields.io/badge/Node.js-18%2B-339933.svg)](https://nodejs.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

</div>

---

## 这是什么

Lilovideo 把视频生成从「赌一次抽卡」变成「可管控的生产线」。

| 你给 | 你得到 |
|---|---|
| 一句话创意 / 一段梗概 | 剧本 → 角色与场景 → 分镜 → 参考图 → 视频片段 → 成片 |

它不是单点式的「文生视频」黑盒，而是一条覆盖全流程的产线：
每个阶段由专职 Agent 负责，前一阶段的产物决定后一阶段的输入，
**所有关键节点都可见、可改、可在修改后继续生成**。

## 核心设计：人机协作边界

系统在 **7 个节点**停下来等用户确认。停点不是随便定的，原则是
**只在「产物不可逆」或「边际成本高」的地方停**：

| 停点 | 阶段 | 为什么在这里停 |
|---|---|---|
| 0 | 剧情与视觉确认 | 决定后续所有生成的方向 |
| 1 | 模型与参数配置 | 直接决定成本量级 |
| 2 | 剧本确认 | 剧本是下游全部产物的依据 |
| 3 | 角色/场景确认 | **不可逆**：所有镜头都依赖角色定稿 |
| 4 | 分镜确认 | 决定镜头数量，**即成本量级** |
| 5 | 参考图确认 | 首帧质量决定视频质量 |
| 6 | 视频片段确认 | **每秒钟都在计费**，必须逐段把关 |
| — | 后期剪辑 | 无需确认，自动拼接出成片 |

> **可回滚的地方不停，不可逆或昂贵的地方才停。**
> 停点太少会让用户拿到不可控的产物、返工更贵；停点太多会烦死用户。
> 这是一个体验与成本的平衡点，不是技术参数。

## 成本与积分

视频生成按秒/按 token 计费，一条成片的成本是**可测量**的，所以这里没有用估算：

| 层 | 做什么 | 位置 |
|---|---|---|
| 成本层 | 记录每次模型调用的**真实用量**（tokens / 秒 / 张）与金额 | `models/cost_store.py` |
| 定价层 | 价格注册表，每条带来源与核实状态；算不出就报"未知"，绝不用 0 冒充免费 | `models/pricing.py` |
| 积分层 | 面向用户的账本：预扣 → 结算 / 退回，每笔记变动后余额 | `models/credits_store.py` |

**几条刻意的设计**：

- **成本数字必须实测取证，不能从二手口径推算。** 项目里真实踩过：
  旧文档写「5 秒片段 ¥7.10」，实测是 **¥5.01**（差额 29%）。计价口径一律以
  官方价目页为准，实测用于交叉验证——两者不一致时如实记录，不静默取一个数。
- **券不能凭空少算。** 未登记缓存价时，缓存命中的 tokens 按普通输入价计费，
  而不是免费；缺失的档位报价返回"未知"，而不是拿邻近档位的价充数。
- **积分账本有强不变式**：`sum(流水) == 余额`，且每笔都带 `balance_after`。
  任何时刻都能一眼验出账本是否被写坏。
- **预扣是幂等的**（`ref = "{session_id}:{stage}"`），阶段重试、断点续跑、
  用户连点都不会重复扣费。余额不足时**在阶段开始前**就拦住，
  而不是跑完几分钟才发现付不起。

模型档位覆盖千问 + 豆包两地 14 个模型 / 31 个可售档位，
内含分辨率与音轨差异，5 秒片段从 10 积分到 262 积分。
完整换算表见 [`docs/阶段文档/积分换算表.md`](docs/阶段文档/积分换算表.md)（由脚本生成，可自校验是否过期）。

## 三种视频生成方式

| 方式 | 说明 |
|---|---|
| **首帧生视频** | 以参考图为起点生成片段，最稳定 |
| **首尾帧生视频** | 当前片段首帧 + 下一片段尾帧，衔接更强 |
| **参考图生视频** | 直接读取角色图与场景图，强调一致性 |

## 架构

```
┌─────────────┐     ┌──────────────────────────────────────────────┐
│  Web 前端    │────▶│  Orchestrator（6 阶段状态机 / 会话持久化）        │
│ (Next.js)   │◀────│   ├─ ScriptWriterAgent      剧本策划            │
└─────────────┘     │   ├─ CharacterDesignerAgent 角色/场景设计        │
                    │   ├─ StoryboardAgent        分镜规划            │
┌─────────────┐     │   ├─ ReferenceGeneratorAgent 参考图生成         │
│  模型服务层   │◀────│   ├─ VideoDirectorAgent     视频生成            │
│ LLM/VLM/图/视│     │   └─ VideoEditorAgent       后期剪辑            │
└─────────────┘     └──────────────────────────────────────────────┘
```

- **后端**：Python + FastAPI。`core/orchestrator.py` 管理 6 阶段状态机与会话状态，
  各 `core/agents/*_agent.py` 实现单阶段逻辑，`models/` 封装各家模型客户端。
- **前端**：Next.js + React + Tailwind。提供创作工作台、阶段确认、参数配置与产物预览。
- 后端默认 `http://localhost:8000`，前端默认 `http://localhost:3000`。

## 一键启动

装好之后，**双击 `start.command`**（macOS）或在终端执行：

```bash
bash scripts/launch.sh
```

它会依次：检查依赖 → 启动后端并等它就绪 → 启动前端 → 自动打开浏览器。
停止用 `bash scripts/stop.sh`。

启动器是**按"第一次用的人会怎么出错"设计的**，所以：

| 情况 | 行为 |
|---|---|
| 依赖没装齐 | 直接告诉你先跑 `install.sh`，而不是跑到一半失败 |
| 服务已经在跑 | 不重复启动，直接打开浏览器（幂等，随便点几次都没事） |
| 只起了一半（比如后端在、前端不在） | **复用已在跑的那一半**，只补起缺的，不会把好的那个杀掉 |
| 端口被别的程序占用 | 说清是哪个端口被谁占了，并给出换端口的命令 |
| 启动超时 | 打印日志末尾 20 行，而不是干等 |
| 停止 | 递归停整棵进程树（`npm` → `next dev` → `next-server`），不留孤儿进程 |

常用参数：

```bash
bash scripts/launch.sh --prod      # 生产模式（先 build，首屏更快）
bash scripts/launch.sh --no-open   # 不自动开浏览器
LILOVIDEO_BACKEND_PORT=8010 LILOVIDEO_FRONTEND_PORT=3010 bash scripts/launch.sh   # 换端口
```

日志位置：`$TMPDIR/lilovideo/backend.log` 与 `frontend.log`。

> **macOS 首次双击若提示"无法打开"**，是因为文件带了下载隔离属性，执行一次即可：
> ```bash
> xattr -dr com.apple.quarantine .
> ```

## 快速开始

### 环境要求

- Python 3.10+（推荐 3.12）
- Node.js 18+ / npm 9+
- ffmpeg（视频拼接与音视频后处理）

### 安装

```bash
# 一键安装（检查依赖、装前后端依赖、生成 config.yaml）
cd src
bash install.sh
cd ..
bash scripts/launch.sh      # 或直接双击 start.command
```

### 手动安装

```bash
# 后端（需要 Python 3.10+，推荐 3.12）
cd src/backend
python3.12 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp config.yaml.example config.yaml   # 然后填入 API Key
python api_server.py                 # http://localhost:8000

# 前端（新终端）
cd src/frontend
npm install
npm run dev -- --webpack             # http://localhost:3000
```

> **关于 `--webpack`**：本项目默认用 Turbopack，但在部分环境下 Turbopack 无法解析
> `lightningcss` 的原生模块。若启动报 `Cannot find module '...lightningcss...'`，
> 请加上 `--webpack` 参数改用 Webpack 模式。

> **如果报原生模块加载错误**（`library load disallowed by system policy`
> 或 `Cannot find native binding`），说明 `node_modules` 里的原生二进制带了
> macOS 隔离属性，执行一次即可：
>
> ```bash
> xattr -dr com.apple.quarantine .
> ```

### 配置模型

后端配置在 `src/backend/config.yaml`，也可在前端「设置」页面修改：

| 平台 | 配置字段 | 用途 |
|---|---|---|
| DashScope（通义） | `dashscope.api_key` | 通义千问、万相 Wan 图像/视频 |
| 火山方舟 ARK | `ark.api_key` | 豆包 Seedream 图像、Seedance 视频 |
| Kling（可灵） | `kling.access_key` / `secret_key` | 可灵视频生成 |
| OpenAI | `openai.api_key` | GPT 文本/视觉 |
| Gemini | `gemini.api_key` | Gemini 文本/视觉 |
| DeepSeek | `deepseek.api_key` | DeepSeek 文本。**注意**：默认配置把它指向火山方舟的兼容接口（用 ARK Key），不是 DeepSeek 官方平台；改回官方只需换 `base_url` 与 Key |

只需填写你实际选用模型所对应的平台密钥。

## 项目结构

```
.
├── src/                     # 代码
│   ├── backend/             # FastAPI 后端
│   │   ├── core/
│   │   │   ├── orchestrator.py  # 6 阶段状态机
│   │   │   └── agents/          # 6 个阶段 Agent
│   │   ├── models/              # 各平台模型客户端
│   │   ├── pipelines/           # 一次性短流程 Pipeline
│   │   ├── api/routers/         # API 路由
│   │   ├── templates/           # 成片渲染模板
│   │   └── code/                # 会话元数据与生成产物
│   ├── frontend/            # Next.js 前端
│   │   ├── app/                 # 页面路由
│   │   ├── components/
│   │   │   ├── stages/          # 6 个阶段的界面组件
│   │   │   └── ...
│   │   └── config/
│   │       ├── brand.ts         # 品牌唯一源（改名只改这里）
│   │       └── models.ts
│   └── install.sh           # 一键安装
├── scripts/                 # 启动 / 停止脚本（launch.sh / stop.sh）
├── docs/                    # 文档
│   ├── PRD/                     # 产品需求文档
│   └── memory/                  # 项目状态与决策记录
├── references/              # 流程与 API 操作手册
└── start.command            # macOS 双击启动入口
```

## 附加能力

除主流程外，还提供一组一次性流水线（无需人工介入、后台执行）：

- **文艺短视频**：旁白配图视频
- **动作迁移**：把动作迁移到人物上
- **数字人口播**：商品/知识口播视频

以及「临时工作台」：单独调用文生图、图生图、视频生成、LLM、VLM。

## 产物

所有任务元数据与生成产物保存在 `src/backend/code/`：

```text
src/backend/code/
├── data/sessions/        # 会话元数据 (JSON)
└── result/
    ├── image/<session>/  # 角色/场景素材 + 分镜参考图
    ├── video/<session>/  # 生成的视频片段
    └── script/           # 剧本/分镜数据
```

## 来源与致谢

本项目的部分基础实现基于以下开源项目（均为 MIT 许可）：

- [XiaoYunQue](https://github.com/Innate-Labs/xiaoyunque) — Copyright (c) 2026 Innate Labs
- [FilmAgent / Video-Claw](https://github.com/HITsz-TMG/FilmAgent) — Copyright (c) 2026 HITsz-TMG

上游版权声明已按 MIT 许可要求保留在 [LICENSE](LICENSE) 中。
品牌体系、产品设计与产品化改造由本项目独立完成，详见 LICENSE 中的说明。

## License

[MIT](LICENSE)
