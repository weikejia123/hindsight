# Hindsight 作为本地统一 Agent 记忆系统 — 可行性分析与分层能力手册

> 生成日期：2026-08-03
> 项目：projects/memory/hindsight（vectorize-io/hindsight fork，wkj-dev 二开分支）
> 上游版本：b5d8439c（main 与 upstream/main 完全同步，落后 0 commit，官方最新）
> 本地部署：Docker 运行中（API localhost:8888 / 控制面板 localhost:9999 / PG 内部 5432）

---

## 一、现状核查结论（先回答"项目是不是最新的"）

| 检查项 | 结果 |
|--------|------|
| 上游同步 | ✅ `main` = `upstream/main` = `b5d8439c`，落后 0 commit，**官方最新代码** |
| 二开分支 | ✅ 当前在 `wkj-dev`，基于 main，领先 2 个 commit（my-docker 部署配置 + README-WAKE V2），无分叉 |
| 文档位置 | ✅ `my-docs/` 存在（20260707-hindsight-docker-deploy-analysis.md、20260707-hindsight-deployment-status.md） |
| 本地服务 | ✅ hindsight-app（8888 API / 9999 面板）Up 8 天，hindsight-db healthy |
| Hermes 接入 | ✅ `memory.provider = hindsight`，bank=hermes，当前 2327 facts，昨日仍在写入 |

结论：**项目健康、官方最新、二开分支规范、本地部署可用。无需任何同步操作。**

---

## 二、Hindsight 本质（一句话定位）

Hindsight 是一个**带学习能力的 Agent 长期记忆系统**：它不只是"存下对话然后搜出来"（RAG），而是每次存储时用 LLM 从原始内容中**提取结构化事实**、维护**实体知识图谱**、并在后台把重复事实**归纳为心智模型**——检索时用语义向量、BM25 全文、图谱关联、时间线四路并行召回再重排。

类比：RAG 是图书馆（存书、按关键词找书）；Hindsight 是大脑（把经历提炼成"事实"、把事实沉淀成"认知"、按关联联想调用）。

---

## 三、Hindsight 的层次能力全景（重点）

从用户视角，Hindsight 的记忆管理能力分 **4 个维度、7 个层次**。每层先说是什么，再说怎么用。

### 维度 A：数据分层 — 记忆内容的 3 种类型

| 类型 | 代码值 | 含义 | 典型例子 | 谁产生 |
|------|--------|------|----------|--------|
| 世界事实 | `world` | 客观知识、偏好、规则、修正、约束 | "用户偏好简洁回答"、"项目用 uv 管理依赖" | retain 提取 |
| 体验事实 | `experience` | agent 实际执行过的动作/经历 | "我部署了 DM8 到 huipu-22" | retain 提取（LLM 标记 assistant→映射为 experience） |
| 观测/心智模型 | `observation` | 从多条事实归纳的证据型结论，带引用来源 | "该项目已三次因同一配置项踩坑" | consolidation 后台归纳 |

**怎么用**：
- 你不需要手动分类——retain 时 LLM 自动判断 world/experience。
- observation 不用你管——后台 consolidation 自动从事实中凝练，检索时优先命中（它代表"认知"而非"记录"）。
- 查询时可按 fact_type 过滤（API 支持 `fact_types` 参数），例如只要世界知识不要个人经历。

### 维度 B：存储分层 — 数据从原始到精炼的 5 级管线

```
Bank（大脑/隔离空间）
 └─ Document（原始输入：对话、文档、git 历史）
     └─ Memory Unit（提取的事实：world/experience）
         ├─ Entity + Entity Link（实体知识图谱：谁/什么/关联谁）
         └─ Observation（归纳的观测，带 evidence 引文 + 时间趋势）
```

| 层 | 是什么 | 怎么用（用户视角） |
|----|--------|-------------------|
| **Bank** | 完全隔离的记忆库，每个 bank 一个"大脑"，可设 mission（身份使命）和 disposition（怀疑/字面/共情 3 项 1-5 分性格） | 一个 agent 一个 bank，或一个项目一个 bank。bank 之间严格隔离，不互相泄漏。disposition 只影响 reflect 推理风格，不影响 recall |
| **Document** | retain 的原始输入，保留全文 | 不需要管理，自动存。可查（documents 列表），是事实的溯源依据 |
| **Memory Unit** | LLM 从 document 提取的原子事实（world/experience），含时间、实体、归属 | 核心查询对象。recall/reflect 都作用于它 |
| **Entity/Link** | 实体（人/项目/工具）及其关系边，形成知识图谱 | 图谱检索策略（graph）用：问"和 X 相关的事"时，从 X 出发沿关系扩散 |
| **Observation** | consolidation 把多条事实折叠成的结论，每条带证据引文（exact quote）+ 时间趋势（递增/稳定/新近） | 自动产生，检索时权重高。反映系统"学到了什么" |

### 维度 C：操作分层 — 4 个核心动词

| 操作 | 方向 | 做什么 | 什么时候用 | 本地现状 |
|------|------|--------|-----------|---------|
| **retain** | 存 | LLM 从输入提取事实+实体+关系写入 | 对话结束、文档入库、git 提交 | Hermes 每轮对话自动 retain |
| **recall** | 查 | 4 策略并行召回（语义向量 / BM25 全文 / 图谱扩散 / 时间线）+ 交叉编码器重排，返回最相关事实 | 每个任务开始时注入相关记忆 | Hermes 每轮自动 recall（budget=mid） |
| **reflect** | 推理 | 把查询 + 相关记忆 + 心智模型交给 LLM，生成有依据的合成回答（不是搜出来，是"想出来"） | 需要跨多段记忆综合判断时 | Hermes 的 `hindsight_reflect` 工具 |
| **consolidate** | 升华 | 后台扫描重复事实 → 折叠成 observation 心智模型 | 完全自动，无需干预 | 运行中 |

**关键区别**：recall 是"把相关记忆摆到你面前"，reflect 是"读完记忆后替你得出结论"。日常上下文注入用 recall（快、省 token），做深度判断用 reflect（慢、需要 LLM）。

### 维度 D：接入分层 — 6 种访问方式

| 接入方式 | 覆盖对象 | 一句话说明 |
|----------|---------|-----------|
| **Hermes native provider** | Hermes Agent | 已启用。pre_llm_call 自动 recall + post_llm_call 自动 retain + 3 个工具 |
| **hindsight-coding-agents**（npm） | Claude Code、Codex、OpenCode、Cursor CLI、Copilot CLI、Grok Build、Kilo、Cline、Antigravity 共 9 种 | 一行安装自动接入，per-repo 记忆 bank，自动从 git 历史+对话建记忆，session 首轮自动 reflect |
| **MCP server** | 任何支持 MCP client 的 agent/IDE | 以标准 MCP 暴露 retain/recall/reflect |
| **REST API + SDK** | 完全自定义接入 | Python/TypeScript/Rust 三语 SDK；任意脚本/agent 可调 |
| **hindsight-cli**（Rust） | 命令行 | 手动 retain/recall/reflect，脚本友好 |
| **Control Plane UI** | 人类 | localhost:9999 面板：看所有 bank、文档、事实、心智模型，可视化管理 |

---

## 四、可行性分析：本地 agent 统一用 Hindsight 当记忆系统

### 结论先行

**可行，且是当前阶段最合理的选择。** 分两条路径，覆盖你本地全部 agent：

- **路径 A（官方直连）**：`npm install -g hindsight-coding-agents` 一行装完，自动识别并接入官方支持的 coding agent。你本地的 **Claude Code（含 claude-code-best fork）** 就在支持清单内。
- **路径 B（标准协议）**：不支持 harness 的 agent（如自研的 **pi**、**DeerFlow**）通过 **MCP server** 或 **REST API + SDK** 接入，工作量一天内可完成。

### 本地 agent 盘点与接入方案

| 本地 agent | 现状 | 接入方式 | 工作量 |
|-----------|------|---------|--------|
| Hermes Agent | ✅ 已接入（provider=hindsight，bank=hermes） | native provider | 已完成 |
| Claude Code（~/.local/bin/claude，含 claude-code-best fork） | 未接入 | hindsight-coding-agents（harness: claude-code） | 5 分钟 |
| pi（@earendil-works/pi-coding-agent，自研 fork） | 未接入 | 路径 B：MCP server 或 REST API | 半天 |
| DeerFlow（projects 内 fork） | 未接入 | 路径 B：REST API + SDK（Python） | 半天 |
| Codex / OpenCode / Cursor 等（未装但可能用） | 未接入 | hindsight-coding-agents | 5 分钟 |

### 推荐的 Bank 架构（统一后端 + 按知识域分层）

**详见专文：`my-docs/20260803-hindsight-bank-architecture.md`**（完整设计 + 配置示例 + 决策点）

核心结论（摘要）：
- **bank = 知识域，不是 agent、也不是 repo**。按业务线聚合，活跃 bank 收敛到 10-20 个，冷项目由 coding-agents 惰性创建兜底（不产生记忆）。
- **三层体系**：L1 个人/通用域（hermes / ops / research / meta，跨 agent 共享）→ L2 项目集群域（coding-agent::yszx / ::ai-agents / ::dev-tools 等，mapPathToBank 目录前缀聚合）→ L3 特殊域（default / test-bank）。
- **共享靠"同 bank 写入"**（配置级 mapPathToBank / bank_id 指向），不靠跨 bank 查询；Hermes 侧多 bank 用脚本路由（机制 B）实现。
- **防混乱四道防线**：域级隔离（防脏）+ 文档溯源（防混）+ 结构化组织（防乱）+ 相关性召回（防杂）。

### 注意事项（坑）

1. **MiniMax 过期只影响 retain**：当前配置 retain 走 MiniMax-M2.7（提取事实），recall/reflect 只用本地 Ollama bge-m3 向量检索。MiniMax key 失效 = 新记忆无法结构化（内容不丢但无事实层），查询不受影响。统一接入多 agent 前建议先确认 retain 通道健康（或换低成本 provider）。
2. **bank 隔离是硬边界**：不能跨 bank 直接查。要共享记忆必须同一 bank 或 API 层聚合，别期待"所有 agent 自动看到彼此的记忆"。
3. **coding-agents 的 git 深度摄取**：默认只读 commit message（gitIngest=message），要全 diff 分析改成 `full`（更准但更慢更贵）。
4. **权限模型**：本地 Docker 部署无鉴权（API 直连 localhost:8888），只在局域网内可信环境用；若暴露公网需加 apiToken。
5. **Harness 归属**：coding-agents 会给每个 document 打 harness 标记（metadata.harness），控制面板按 agent 显示 logo——接入多个 agent 后天然可区分"谁记的"。

---

## 五、落地路线图

| 优先级 | 行动 | 说明 |
|:------:|------|------|
| P0 | `npm install -g hindsight-coding-agents && hindsight-coding-agents install` | 接入 Claude Code（及未来装的 Codex/OpenCode），per-repo 记忆自动开始工作 |
| P0 | 确认 retain LLM 通道健康 | 检查 MiniMax key 是否有效；失效则配置低成本 provider（如 ollama 本地模型或 groq） |
| P1 | pi 接入（路径 B） | 若 pi 支持 MCP client → 走 local-mcp；否则用 REST API + Python/TS SDK 写薄封装 |
| P1 | DeerFlow 接入（路径 B） | 同上，Python SDK 最直接 |
| P2 | 建立 bank 管理规范 | 文档化 bank 命名（hermes / coding-agent::<repo> / pi / deerflow）、哪些 bank 可共享、控制面板使用习惯 |

---

## 六、附：关键源码位置速查

| 关注点 | 位置 |
|--------|------|
| 记忆引擎（retain/recall/reflect 编排） | `hindsight-api-slim/hindsight_api/engine/memory_engine.py` |
| 事实提取（world/experience 分类） | `hindsight-api-slim/hindsight_api/engine/retain/fact_extraction.py`（fact_type 判定在 ~L1478-1487） |
| 检索 4 策略（semantic/bm25/graph/temporal） | `hindsight-api-slim/hindsight_api/engine/search/retrieval.py` |
| 观测/心智模型（observation + evidence + trends） | `hindsight-api-slim/hindsight_api/engine/reflect/observations.py` |
| 归纳升华（consolidation） | `hindsight-api-slim/hindsight_api/engine/consolidation/` |
| REST API 路由 | `hindsight-api-slim/hindsight_api/api/http.py` |
| MCP server | `hindsight-api-slim/hindsight_api/api/mcp.py` |
| coding agents 集成（9 种 harness） | `hindsight-integrations/coding-agents/`（npm 包 `hindsight-coding-agents`） |
| Hermes 集成文档 | `skills/hindsight-docs/references/sdks/integrations/hermes.md` |
