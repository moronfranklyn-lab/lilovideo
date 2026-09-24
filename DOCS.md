# 文档索引

Lilovideo 的全部项目文档。代码在 `src/`，文档在 `docs/`。

## 项目文档

| 文档 | 位置 | 内容 |
| --- | --- | --- |
| 产品需求文档 | [docs/PRD/Lilovideo-PRD.md](docs/PRD/Lilovideo-PRD.md) | 目标用户、核心任务、停点设计、质量底线、交付优先级 |
| 项目状态 | [docs/memory/项目状态.md](docs/memory/项目状态.md) | 当前阶段、决策台账、待确认问题、环境台账 |
| 上下文备忘 | [docs/memory/上下文备忘.md](docs/memory/上下文备忘.md) | 路径约定、常用命令、环境坑与绕过方法 |
| 记忆层索引 | [docs/memory/README.md](docs/memory/README.md) | 记忆文件阅读顺序与维护规则 |
| 阶段文档 | [docs/阶段文档/阶段2-后端MVP.md](docs/阶段文档/阶段2-后端MVP.md) | 后端 MVP 的技术方案、产出清单、验收条件 |

## 代码

| 目录 | 内容 |
| --- | --- |
| [src/backend](src/backend) | FastAPI 后端：6 阶段状态机、6 个阶段 Agent、各平台模型客户端 |
| [src/frontend](src/frontend) | Next.js 前端：创作工作台、阶段界面、设置页 |
| [src/install.sh](src/install.sh) | 一键安装脚本 |

## 快速启动

```bash
# 安装
cd src && bash install.sh

# 后端
cd src/backend && .venv/bin/python api_server.py      # http://localhost:8000

# 前端（新终端）
cd src/frontend && npm run dev -- --webpack            # http://localhost:3000
```

## 开发状态

当前处于**阶段 2 后端 MVP**。后端运行环境已搭好并验证可启动，等待配置模型密钥后做首次真实生成。

详见 [docs/memory/项目状态.md](docs/memory/项目状态.md)。
