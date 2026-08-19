# Hindsight 项目规约

> 本文件由 Claude Code (claude.ai/code) 读取，用于指导 AI agent 在 Hindsight 项目中的工作。
>
> 内部版本: V1-20260819

---

## 项目身份

- **项目名称**: Hindsight — Agent Memory That Learns
- **用途**: Agent 记忆系统，让 Agent 不仅记住还能学习，超越 RAG 和知识图谱
- **应用场景**: AI Agent 跨会话记忆、用户画像持久化、行为学习
- **技术栈**: Python (FastAPI) | TypeScript (Next.js) | PostgreSQL (pgvector) | LLM (OpenAI/Anthropic/Gemini/Groq/MiniMax/Ollama等)
- **内部版本**: V2-20260803（上游）
- **Fork 版本**: V1-20260819（本地二开）
- **依赖**: Docker（推荐）或 `pip install hindsight-all`（嵌入式）
- **部署配置**: `/Users/weikejia/CODE/my-agent-group/docker/compose/hindsight/`（统一在 my-agent-group 根 `docker/` 目录管理，代码目录不存映射数据）

---

## 项目结构

### Monorepo 拓扑

```
hindsight/
├── hindsight-api-slim/          # 核心 FastAPI 服务器（Python, uv）
│   ├── hindsight_api/
│   │   ├── api/                 # API 路由层
│   │   ├── engine/              # 核心引擎
│   │   ├── db/                  # 数据库层（Alembic 迁移）
│   │   └── ...
│   └── tests/                   # 单元测试
├── hindsight-control-plane/     # 管理控制面板（Next.js, npm）
├── hindsight-cli/               # CLI 工具（Rust, cargo）
├── hindsight-clients/           # 生成的 SDK 客户端
├── hindsight-docs/              # Docusaurus 文档站
├── hindsight-integrations/      # 框架集成
├── hindsight-dev/               # 开发工具和基准测试
├── my-docs/                     # 项目文档
│   ├── 11-分析报告/              # 分析报告存储目录
└── docker/                      # Docker 部署配置
```

### 核心引擎模块

**hindsight-api-slim/hindsight_api/engine/**

| 模块 | 职责 |
|------|------|
| `memory_engine.py` | 主编排器，协调 retain/recall/reflect 操作 |
| `llm_wrapper.py` | LLM 抽象层，支持多种提供商 |
| `embeddings.py` | 嵌入生成（本地 sentence-transformers 或 TEI） |
| `cross_encoder.py` | 交叉编码器重排序 |
| `entity_resolver.py` | 实体提取和标准化 |
| `query_analyzer.py` | 查询意图分析 |
| `retain/` | 记忆摄取管道（orchestrator/fact_extraction/link_utils） |
| `search/` | 多策略检索（retrieval/graph_retrieval/link_expansion_retrieval/fusion/reranking） |
| `reflect/` | 思考工具调用（lookup/recall/learn/expand） |

### API 层

**hindsight-api-slim/hindsight_api/api/**

- `http.py`: FastAPI HTTP 路由
- `mcp.py`: Model Context Protocol 服务器实现

**主要端点**:
- `POST /v1/default/banks/{bank_id}/memories/retain` — 存储记忆
- `GET /v1/default/banks/{bank_id}/memories/recall` — 检索记忆
- `POST /v1/default/banks/{bank_id}/reflect` — 反思推理
- `GET /v1/default/banks/{bank_id}/memories/list` — 列出记忆
- `GET /v1/default/banks/{bank_id}/graph` — 获取图数据
- `GET /v1/default/banks` — 列出所有 banks
- `POST /v1/default/banks` — 创建 bank

### 数据库

PostgreSQL + pgvector。Schema 管理通过 `hindsight-api-slim/hindsight_api/alembic/` 中的 Alembic 迁移。

**关键表**:
- `banks` — 记忆存储单元（类似"大脑"）
- `memory_units` — 记忆单元
- `documents` — 文档
- `entities` — 实体
- `entity_links` — 实体链接

---

## 开发工作流

### 本地开发

```bash
# 启动 API 服务器和控制面板
./scripts/dev/start.sh

# 仅启动 API 服务器
./scripts/dev/start-api.sh

# 运行测试
cd hindsight-api-slim && uv run pytest tests/

# 代码检查和格式化
cd hindsight-api-slim && uv run ruff check .
cd hindsight-api-slim && uv run ruff format .

# 类型检查
cd hindsight-api-slim && uv run ty check hindsight_api/
```

### 数据库迁移

```bash
# 运行迁移（基础 schema + 所有租户）
uv run hindsight-admin run-db-migration

# 运行迁移（特定租户 schema）
uv run hindsight-admin run-db-migration --schema tenant_xyz
```

### 生成客户端和 OpenAPI

```bash
# 生成 OpenAPI 规范
./scripts/generate-openapi.sh

# 生成所有客户端 SDK
./scripts/generate-clients.sh
```

---

## 核心概念

### Memory Banks（记忆库）

- 每个 bank 是一个隔离的记忆存储（类似一个用户的"大脑"）
- Banks 有 disposition（怀疑度、字面主义、同理心 1-5），影响 reflect
- Banks 可能有背景上下文
- Bank 隔离严格 — 无跨 bank 数据泄露

### Fact Types（事实类型）

- `world` — 世界知识（"天空是蓝色的"）
- `experience` — 个人经历（"我在 2023 年去过巴黎"）
- `observation` — 观察事实（从文档中提取的稳定事实，如"用户偏好函数式编程"）

### Retain/Recall/Reflect

- **Retain**: 存储记忆，提取事实/实体/关系
- **Recall**: 通过 4 种策略检索记忆（语义、BM25、图、时间）+ 重排序
- **Reflect**: 基于记忆和 mental models 的推理思考

---

## 代码规范

### Python 代码风格

参考 `.claude/skills/code-review/SKILL.md` 的完整规范。

**关键原则**:
- 类型安全：使用类型注解，避免 `Any`
- 避免原始字典：使用 Pydantic 模型
- 不使用多元素元组返回：返回命名元组或数据类
- 代码审查：在提交前运行 `/code-review`

### 测试规范

- 大多数测试是确定性的（MockLLM、纯函数） — 直接断言
- 验证 LLM 行为的测试使用真实 LLM + LLM-as-judge
- Judge 模型与测试提供者独立（默认 Gemini）

**Judge 测试模式**:
```python
# 1. 标记为 LLM 核心测试
pytestmark = pytest.mark.hs_llm_core

# 2. 使用真实 LLM
facts_summary = "\n".join(f"- [{f.fact_type}] {f.fact}" for f in facts)
await assert_meets_criteria(
    response=facts_summary,
    criteria="...",
    context="...",
)

# 3. Judge 模型与测试提供者无关
```

### TypeScript/Next.js 代码风格

- 参考 `hindsight-control-plane/src/app/api/` 中的 TypeScript 规范
- 使用 shadcn/ui 组件库
- API 代理到 dataplane API

---

## 配置系统

配置遵循层级系统：**全局（env vars）→ 租户（扩展）→ Bank（数据库）**

**可配置字段**（可跨租户/Bank 覆盖）:
- LLM 设置（提供商、模型、API key、base URL）
- 操作特定设置（retain 模式、chunk size 等）
- 按客户/Bank 变化的特性开关

**静态字段**（服务器级别）:
- 基础设施设置（数据库 URL、端口、主机）
- 全局限制（最大并发操作）
- 系统级特性开关

---

## 添加新 API 配置

1. **config.py**: 添加 `ENV_*` 常量和 `DEFAULT_*` 常量，更新 `HindsightConfig` 数据类，标记为可配置
2. **main.py**: 如需 CLI 标志，添加参数解析
3. **MemoryEngine**: 使用 `ConfigResolver.get_bank_config()` 获取层级配置
4. **文档**: 更新 `hindsight-docs/docs/developer/configuration.md`
5. **.env.example**: 添加环境变量模板

---

## API 设计原则

- 所有端点在单个 bank 上操作
- 多 bank 查询是客户端的责任
- Disposition 特性仅影响 reflect，不影响 recall

### Control Plane 代理

添加或修改 dataplane API 参数时，必须更新 control plane 代理：

1. **API 路由** (`hindsight-control-plane/src/app/api/`): 更新代理调用
2. **客户端类型** (`hindsight-control-plane/src/lib/api.ts`): 更新 TypeScript 类型定义
3. **检查清单**: 参数提取 → 传递给 SDK → 更新类型定义 → 更新 UI 组件

---

## 添加新集成

每个新集成必须满足：

1. **测试要求** — 模拟或测试外部系统
2. **CI 作业** — 添加 `.github/workflows/test.yml` 条目
3. **发布流程** — 添加到 `VALID_INTEGRATIONS` 数组
4. **代码标准** — 遵循项目规范

---

## 环境设置

```bash
cp .env.example .env
# 编辑 .env，配置 LLM 提供商/模型和凭证

# Python 依赖
uv sync --directory hindsight-api-slim/

# Node 依赖
npm install
```

**常用 LLM 设置**:
- `HINDSIGHT_API_LLM_PROVIDER`: openai, anthropic, gemini, groq, minimax, ollama, lmstudio
- `HINDSIGHT_API_LLM_API_KEY`: API key
- `HINDSIGHT_API_LLM_MODEL`: 模型名称（提供者默认）

**可选设置**:
- `HINDSIGHT_API_EMBEDDINGS_PROVIDER`: local（默认）或 tei
- `HINDSIGHT_API_RERANKER_PROVIDER`: local（默认）或 tei
- `HINDSIGHT_API_DATABASE_URL`: 外部 PostgreSQL（默认使用嵌入式 pg0）

---

## 分析报告目录

**路径**: `/Users/weikejia/CODE/my-agent-group/projects/memory/hindsight/my-docs/11-分析报告/`

**用途**: 存储项目分析报告，包括：
- 架构分析
- API 分析
- 数据库分析
- 性能分析
- 功能分析

**文件命名规范**:
- 格式: `YYYYMMDD-NNN-主题.md`
- 示例: `20260819-001-hindsight-api-endpoint-analysis.md`

---

## Agent 工作指南

### 工作流程

1. **理解项目** — 读取 `CLAUDE.md`、`README-WAKE.md` 和本文档
2. **分析需求** — 理解用户对 hindsight 数据库管理工具的需求
3. **生成报告** — 将分析报告写入 `my-docs/11-分析报告/`
4. **编写代码** — 遵循项目代码规范
5. **测试验证** — 运行测试和代码检查
6. **更新文档** — 如有变更，更新相关文档
7. **提交代码** — 通过 `git add && git commit` 提交

### 沟通约定

- **项目规约**: 确定的、明确的、不可变更的规则（如代码风格、目录结构、开发流程）
- **设计决策**: 可能变更的、需要讨论的方案
- **待确认**: 需要用户确认的方案

### 文档要求

- 所有文档必须原子提交
- 单一事实来源
- 精确术语，不使用模糊隐喻
- 文档与代码同步更新

---

## 相关文档

- **CLAUDE.md**: 项目文档和编码约定（详细规范）
- **README-WAKE.md**: 项目定位和结构（中文）
- **CONVENTIONS.md**: 完整规约（不自动注入）
- **CODE_OF_CONDUCT.md**: 行为准则
- **.claude/skills/code-review/SKILL.md**: 代码审查规范
