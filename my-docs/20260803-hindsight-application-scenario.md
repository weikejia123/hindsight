# Hindsight 多 Agent 协作记忆：应用场景与源码能力对照

> 版本: v0.8.6-wkj / coding-agents v0.0.1（上游 2026-08-03 发布）/ 2026-08-03
> 视角: 用户视角（魏可佳的实际使用场景）
> 方法: 全部结论来自源码实查（hindsight-integrations/coding-agents/ + hindsight_api/），不是文档转述
> 姊妹篇: 20260803-fact-type-explanation.md（三种记忆类型的概念基础）

---

## 一、你的工作场景（原话 + 联想）

**原话**：
- 用 Hermes agent 做整体工作管理（hermes cli + 飞书发送消息）
- 开发代码时主要用 pi agent、claude code、grok build 三种 agent
- 本地几百个项目，大部分是研究参考，只有小部分是开发

**联想出的核心问题**（把场景翻译成记忆系统的需求）：

| # | 问题 | 本质 |
|---|------|------|
| Q1 | 几百个项目，大部分只看不写 —— 怎么不为它们付出记忆成本？ | 惰性建 bank |
| Q2 | 三个开发 agent 交替用同一个项目 —— 记忆会不会各记各的？ | 跨 agent 共享 bank |
| Q3 | 不同 agent 记的东西怎么区分来源？ | harness 标记 |
| Q4 | 开发 agent 怎么在会话开始时自动带上项目上下文？ | 会话注入 |
| Q5 | 会话结束后的经历怎么沉淀下来？ | 转录 retain |
| Q6 | Hermes 的管理记忆（world）和开发 agent 的操作记忆（experience）怎么不互相污染？ | bank 隔离 |
| Q7 | pi 不在官方支持列表里 —— 还能接入吗？ | MCP / REST |

---

## 二、源码给出的答案（逐题对照）

### Q1: 几百个项目怎么不为冷项目付费？—— 惰性建 bank（seed 流）

`src/core/seed.ts` + `src/core/session-start.ts:56-58`

```
The session banner: ... plus the repo's bank. Shown on EVERY session start;
"learning" while the bank is cold (first ingest running), "remembering" once the bank is warm.
```

**机制**：bank 是惰性的——只有当你**真正打开一个仓库开始干活**，且该 bank 还是空的，才触发首次 seed（git log 灌入 commit message 历史）。几百个研究参考项目**永远不会建 bank、永远不产生记忆写入**。冷项目零成本。

这正好回答你的场景：几百个项目里大部分"只看不写"，系统不会为它们建记忆。

### Q2: 三个 agent 交替开发同一个项目，记忆共享吗？—— 默认共享

`src/core/bank.ts:35-40`（DEFAULT_TEMPLATE 的设计意图）

```typescript
// Harness-NEUTRAL default so every coding agent (Claude, Codex, Cursor, opencode)
// shares ONE bank per repo — switch agents, keep your memory.
// Deliberately NOT `{harness}::…` (that would split memory per agent, defeating cross-agent sharing).
const DEFAULT_TEMPLATE = "coding-agent::{gitProject}";
```

**机制**：默认模板 `coding-agent::{gitProject}` **故意不含 {harness}**——claude code 和 grok build 在同一个 repo 工作时，写入**同一个 bank**。今天用 grok 改的代码，明天用 claude 继续时，记忆都在。worktree-aware：一个 repo 的所有 worktree 共享同一 bank。

> 如果你想按 agent 隔离（比如测试阶段不想混），改 template 为 `{harness}-{gitProject}` 即可（bank.ts 注释里给了这个选项）。

### Q3: 不同 agent 记的东西怎么区分来源？—— metadata.harness + 归因头

- 每条 document 自动打 `metadata.harness` 标记（哪个 agent 记的）
- `src/core/attribution.ts`：**VISIBLE ATTRIBUTION**——agent 引用记忆时必须在回复里显示 `> 🧠 **Using Hindsight Memories** — {具体事实}`，让用户**看得见** Hindsight 在起作用，而不是默默注入

```typescript
// attribution.ts 核心规则
"WHEN IN DOUBT, EMIT. Over-attribution is far better than invisible value."
"Name the specific facts in the summary — not a meta-statement like 'using memory.'"
"如果记忆相关但已过时，也要展示并明说 'memory said X, but the code now shows Y'"
```

### Q4: 会话开始自动带上下文？—— sessionStart hook 三段生命周期

`src/harness/hook-lifecycle.ts:25` + `src/core/session-start.ts`

每个 agent 的接入 = 三个 hook（生命周期契约统一，不会漂移）：

```
sessionStart  → 会话开始：banner 显示 bank + 后台 auto-reflect 注入
prompt        → 每轮用户提问：recall 召回相关记忆 + knowledge pages 注入
stop          → 会话结束：读 transcript → retain 写回（conversation:<sessionId>）
```

- 会话首轮 auto-reflect：把该 repo 的跨会话综合（observation）注入，让 agent 开局就知道项目背景
- 每轮 prompt 注入：语义召回相关记忆（world 约定 + experience 经历 + observation 规律）

### Q5: 会话经历怎么沉淀？—— stop hook 转录 retain

`src/core/retain-hook.ts:50-51`

```typescript
// Pure retain logic: read the transcript, and if it has any usable turns, upsert the
// conversation under `conversation:<sessionId>`.
```

**机制**：会话结束后读取 agent 的 transcript（JSONL 转录文件，每个 harness 有独立 parser：transcript-grok.ts / transcript-claude.ts / transcript-codex.ts 等），归一化后写入 bank，文档 id = `conversation:<sessionId>`。**无需手动 ingest**，全自动。

### Q6: Hermes 管理记忆 vs 开发记忆怎么隔离？—— bank 隔离

- Hermes（记忆 provider）→ `hermes` bank：world 为主（项目知识、偏好、规则、运维事实）
- 开发 agent → `coding-agent::<gitProject>` bank：experience 为主（改了什么、发现了什么）
- **bank 是唯一隔离维度**（所有表挂 bank_id），跨 bank 数据不泄漏——Hermes 的 world 知识不会污染开发 bank，反之亦然

### Q7: pi 不在官方 9 种里，怎么接入？—— MCP server / REST

官方支持 7 种 hook harness（claude-code / codex / antigravity-cli / cursor-cli / copilot-cli / devin-cli / grok-build）+ opencode/kilo 插件。**pi 不在其中**。

但源码提供两条通用路径（与官方 harness 并列）：
1. **MCP server**（`src/mcp-server.ts`）：任何 MCP client 都能接入，pi 作为 MCP client 连上即可
2. **REST + SDK**（hindsight-client）：代码里直接调 retain/recall/reflect（hindsight-bank 脚本方案，2026-08-03 规划文档里已有）

> 局限如实说：pi 走 MCP/REST 就没有官方的"会话自动注入 + 结束转录"生命周期（那些是 harness hook 特有的）。需要自己写小脚本：会话开始 recall 一次、结束 retain 一次。

---

## 三、知识库注入（07-30 新能力，和你关系最大）

`src/core/knowledge-injection.ts` —— 基于新增的 `knowledge_pages` 表（alembic a9b8c7d6e5f4）：

注入给 agent 的工具：
```
- hindsight_search_knowledge_pages(query) — FIRST STOP for any question the
  knowledge might answer (components, conventions, past decisions, initiatives)
- hindsight_list_knowledge_pages / hindsight_read_knowledge_page — 查项目知识库
- hindsight_reflect(query) — 当 pages 太浅、需要 WHY 时
- 新决策/约定 → record it as a tracked page（主动沉淀项目知识）
```

**对你的意义**：你的几百个项目里，小部分开发项目可以把**项目级知识**（架构决策、约定、踩坑记录）沉淀成 knowledge pages——agent 开发时 FIRST STOP 就是查知识库，而不是重新从代码里推断。这正是"研究参考 vs 开发"的转化：研究参考项目可以只读，开发项目沉淀 pages。

---

## 四、三种类型在你场景中的角色（连接 fact-type 文档）

| 类型 | 谁产生 | 你的场景实例 | bank |
|------|--------|-------------|------|
| world | Hermes retain / 开发 agent 提取的用户世界事实 | "用户偏好命令行工具"、"项目在 wkj-dev 分支开发" | hermes、coding-agent::* |
| experience | 开发 agent 的操作（transcript 转录） | "grok 改了 deer-flow 的搜索提供者"、"claude 发现 X bug" | coding-agent::* |
| observation | consolidation 自动归纳 | "该项目近期常在依赖版本上出问题"（从多次 experience 归纳） | coding-agent::* |

**flow**：开发 agent 干活（experience）→ stop hook 转录 → consolidation 后台归纳成 observation → 下个会话 sessionStart 注入 observation → 另一个 agent（甚至 Hermes）接着干时带着全局认识。

---

## 五、落地配置建议（coding-agent.json）

```jsonc
{
  "apiUrl": "http://localhost:8888",        // 本地 API，无鉴权
  "mapPathToBank": {
    // 最长前缀匹配：研究参考目录统一归一个只读 bank（或不建）
    "/Users/weikejia/CODE/my-agent-group/projects/open/": "research-ref",
    "/Users/weikejia/CODE/my-agent-group/projects/self/": "self-dev",
    "/Users/weikejia/CODE/my-agent-group/projects/yszx/": "coding-agent::yszx"  // 业务线聚合
  },
  "gitIngest": "message",                    // 默认：commit message 历史，便宜
  "harnesses": {
    "grok-build": { },                       // 三种 agent 默认共享 coding-agent::<repo>
    "claude-code": { },
    "pi": { "bankId": "pi" }                 // pi 走 MCP/REST 时用独立 bank 或共享
  },
  "banks": {
    "coding-agent::secret-client": { "disabled": true }   // 敏感项目不记
  }
}
```

---

## 六、总结：源码能力如何解决你的问题

| 你的痛点 | 源码方案 | 状态 |
|---------|---------|------|
| 几百项目大部分冷 | 惰性建 bank（seed 流） | ✅ 开箱即用 |
| 三 agent 交替开发 | harness-neutral 共享 bank | ✅ 默认行为 |
| 记忆来源区分 | metadata.harness + 归因头 | ✅ 自动 |
| 开局带上下文 | sessionStart auto-reflect + prompt recall | ✅ 自动 |
| 经历沉淀 | stop hook 转录 retain | ✅ 自动 |
| Hermes/开发隔离 | bank 隔离 | ✅ 架构保证 |
| pi 接入 | MCP server / REST（无官方生命周期） | ⚠️ 需自建脚本 |
| 项目知识沉淀 | knowledge_pages + 注入工具 | ✅ v0.8.6 新功能 |

**一句话**：官方集成解决的是"**同一批开发 agent 在几百个项目里自动记忆且不互相污染**"——惰性建 bank 管冷热、harness-neutral 管共享、hook 生命周期管自动存取、bank 隔离管域。你的场景里唯一需要自己动手的是 **pi 的接入**（走 MCP/REST + 自建会话注入/转录小脚本）。

---

## 附：源码位置速查

| 关注点 | 位置 |
|--------|------|
| bank 动态解析（mapPathToBank 最长前缀） | hindsight-integrations/coding-agents/src/core/bank.ts |
| 配置项（gitIngest/harnesses/banks） | src/core/config.ts |
| 会话三段生命周期契约 | src/harness/hook-lifecycle.ts |
| 会话开始注入 | src/core/session-start.ts |
| 会话结束转录 retain | src/core/retain-hook.ts |
| git 历史 ingest（message/full） | src/core/git.ts |
| 归因头（可见性） | src/core/attribution.ts |
| 惰性建 bank（seed 流） | src/core/seed.ts |
| knowledge pages 注入工具 | src/core/knowledge-injection.ts |
| grok build hook（你用的 agent） | src/grok-hook.ts → runHarnessPrompt("grok-build") |
| MCP server（pi 接入路径） | src/mcp-server.ts |
