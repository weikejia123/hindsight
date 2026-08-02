# Hindsight Bank 架构设计 V2 — 多 Agent 共享记忆方案

> 生成日期：2026-08-03（V2 迭代，用户已确认 3 项核心决策）
> 状态：方案定稿待执行
> 关联：20260803-hindsight-unified-memory-feasibility.md（总体可行性）

---

## 一、已确认的决策（用户拍板）

| # | 决策 | 含义 |
|---|------|------|
| 1 | **按业务线聚合** | 项目记忆不按 repo 分，按业务线收敛到 5-10 个集群 bank |
| 2 | **ops 独立 bank，共享重要** | 运维知识单独建 bank，跨 agent 共享 |
| 3 | **开发 agent 单独 bank** | 开发工作由 pi + claude code 执行，开发域与通用域分开，开发 agent 有独立记忆空间 |

**新增的关键事实**（用户工作分工）：
- 通用工作（个人助理、运维、研究、知识管理、项目治理）→ **Hermes**
- 开发工作（代码开发、项目实现）→ **pi agent + claude code agent**
- 开发域记忆与通用域记忆**必须分离**——Hermes 的通用知识不混入项目开发记忆，项目开发记忆也不混入 Hermes 个人记忆

---

## 二、设计原则（V2 修订）

| # | 原则 | 说明 |
|---|------|------|
| 1 | **bank = 知识域** | 不按 agent 也不按 repo，按"域"（通用/运维/研究/项目业务线/agent 行为） |
| 2 | **通用域与开发域硬分离** | Hermes 的工作流（通用）与 pi/claude 的工作流（开发）是两条线，bank 分开 |
| 3 | **项目业务知识共享，agent 行为记忆独立** | 同一项目的业务上下文（表结构、规范、决策）pi 和 claude code 共享；各自"怎么被用"的行为记忆独立 |
| 4 | **共享靠"同 bank 写入"** | 配置级（mapPathToBank / bank_id），不靠跨 bank 查询 |
| 5 | **活跃 bank 收敛 10-20 个，冷项目零成本** | coding-agents 惰性建 bank，不活跃项目不产生记忆 |

---

## 三、V2 架构：三层 bank 体系

```
Hindsight 服务（本地 Docker 8888，统一后端）
│
├─ L1 通用域（Hermes 主导，4 个 bank）
│   ├─ hermes     — 个人助理：日常对话、偏好、行为规范（已有 2327 facts）
│   ├─ ops        — 运维：服务器/Docker/网络/数据库 ★用户确认独立
│   ├─ research   — 研究/学习/技术调研沉淀
│   └─ meta       — 治理：my-agent-group 规范、流程决策（可选）
│
├─ L2 开发域（pi + claude code 主导，双轨制）
│   ├─ 【项目记忆轨】业务线集群 bank（pi + claude code 共享）
│   │   ├─ coding-agent::my-agent-group   单体管理仓库
│   │   ├─ coding-agent::yszx             客户业务集群（DM8/交付规范）
│   │   ├─ coding-agent::ai-agents        AI agent 开发域
│   │   ├─ coding-agent::dev-tools        工具链开发域
│   │   ├─ coding-agent::admin-apps       管理面板/知识库应用
│   │   └─ ...（未映射路径 → 默认 per-repo 模板兜底）
│   │
│   └─ 【agent 记忆轨】开发 agent 个人 bank（各自独立）★用户确认
│       ├─ pi           — pi 的使用偏好、开发习惯、踩坑记录
│       └─ claude-code  — claude code 的使用偏好、开发习惯
│
└─ L3 特殊域
    ├─ default     — 批量导入/临时（保留）
    └─ test-bank   — 测试遗留（删除）
```

### 为什么开发域要"双轨制"（项目记忆 + agent 记忆）

**项目记忆轨（共享）**：pi 和 claude code 在同一个项目（如 yszx）工作时，写入同一个 `coding-agent::yszx` bank。理由：
- 项目业务上下文（DM8 表结构、客户规范、历史决策）是**项目资产**，不属于任何单一 agent
- 用户用 pi 做 A 功能、claude code 做 B 功能时，两边共享业务记忆，避免各学一遍
- 来源不混淆：coding-agents 自动给每条 document 打 `metadata.harness` 标记（claude-code / codex / ...），控制面板按 agent 显示——**共享不等于混淆**

**agent 记忆轨（独立）**：pi 的"用户怎么配置我、我的版本约定、我踩过的坑"与 claude code 的同类记忆**必须分开**。理由：
- 两个 agent 的行为模式、配置体系、使用习惯完全不同
- 混在一起会造成"pi 的偏好被 claude code 错误引用"

---

## 四、写入/读取矩阵（谁写谁读，一目了然）

| bank | 写入者 | 读取者 | 配置方式 |
|------|--------|--------|---------|
| hermes | Hermes（自动 retain） | Hermes | native provider（现状） |
| ops | Hermes 运维任务 | **所有 agent** | Hermes 写 + hindsight-bank 脚本路由；开发 agent 经 MCP/REST 读 |
| research | Hermes、claude code | 所有 agent | 同上 |
| meta | Hermes | 所有 agent | 同上 |
| coding-agent::\* | pi、claude code（共享） | pi、claude code；Hermes 跨读 | coding-agents mapPathToBank |
| pi | pi（接入后自动 retain） | pi；Hermes 跨读 | pi 走 MCP/REST，bank_id=pi |
| claude-code | claude code（coding-agents harness） | claude code；Hermes 跨读 | coding-agents 静态 bankId 或 harness 路由 |
| default | 批量导入 | 手动 | import API |

**跨域读取规则**（谁可以读谁的）：
- 开发 agent 读 ops/research：✅ 部署时要查运维知识、调研时要查研究沉淀——**这正是共享的价值**
- Hermes 读 coding-agent::\*：✅ 回答"yszx 项目现在什么状态"这类跨项目问题（用 hindsight-bank 脚本，机制 C）
- 开发 agent 读 hermes：❌ 个人助理记忆不共享（隐私/防噪）
- pi 读 claude-code（或反之）：❌ agent 行为记忆互不共享

---

## 五、项目集群划分（mapPathToBank 配置）

```jsonc
// ~/.hindsight/coding-agent.json（pi 和 claude code 共用同一份配置）
{
  "apiUrl": "http://localhost:8888",
  "mapPathToBank": {
    "/Users/weikejia/CODE/my-agent-group/projects/yszx/": "coding-agent::yszx",
    "/Users/weikejia/CODE/my-agent-group/projects/coder-agent/": "coding-agent::ai-agents",
    "/Users/weikejia/CODE/my-agent-group/projects/standard-agent/": "coding-agent::ai-agents",
    "/Users/weikejia/CODE/my-agent-group/projects/memory/": "coding-agent::ai-agents",
    "/Users/weikejia/CODE/my-agent-group/projects/skills/": "coding-agent::ai-agents",
    "/Users/weikejia/CODE/my-agent-group/projects/dev-tools/": "coding-agent::dev-tools",
    "/Users/weikejia/CODE/my-agent-group/projects/tools/": "coding-agent::dev-tools",
    "/Users/weikejia/CODE/my-agent-group/projects/web-tools/": "coding-agent::dev-tools",
    "/Users/weikejia/CODE/my-agent-group/projects/main-admin-apps/": "coding-agent::admin-apps",
    "/Users/weikejia/CODE/my-agent-group/projects/gshare-apps/": "coding-agent::admin-apps"
  },
  "harnesses": {
    "claude-code": { "bankId": "claude-code" }  // agent 记忆轨：harness 可覆盖目标 bank
  }
}
```

> 注：claude-code 的"agent 个人记忆"可通过 harness 级配置把非项目场景（如无 git 仓库的会话）路由到 `claude-code` bank；项目场景仍走 mapPathToBank 聚合。pi 的"agent 个人记忆"在 pi 接入时用 bank_id=pi 实现（路径 B）。

**聚合逻辑（业务线优先，已确认）**：
- 同一客户/业务（yszx 系列 9 项目）→ 一个 bank，共享 DM8 表结构、数据模型、交付规范经验
- 同一技术域（AI agent 开发：pi、deerflow、claude-code fork、skills）→ 一个 bank，agent 开发经验互通
- 工具链/管理面板 → 各自聚类
- 不映射路径（open/ 参考、冷项目）→ per-repo 模板兜底，惰性创建

---

## 六、共享机制（3 种，按场景选）

| 机制 | 做法 | 适用场景 | 成本 |
|------|------|---------|------|
| **A. 同 bank 共享（主推）** | 多 agent 配置指向同一 bank | 项目集群（pi+claude 共享）、ops/research | 配置级，零代码 |
| **B. 写入路由（辅）** | REST API/SDK 显式 retain 到目标 bank | Hermes 运维知识 → ops、研究结论 → research | 小脚本（hindsight-bank），半天 |
| **C. 读取聚合（高级）** | 客户端循环多 bank recall 合并 | Hermes 跨读开发域、跨域综合查询 | SDK 封装，1 天 |

**落地组合**：A 为主（coding-agents 配置即共享），B 为辅（Hermes 定向沉淀运维/研究知识），C 在 P2 后按需启用（Hermes 回答项目状态类问题）。

---

## 七、Hermes 侧接入方案（现实约束）

**约束**：Hermes native provider 单 bank（`bank_id: hermes`），工具不带 bank 参数。

| 需求 | 方案 | 实现 |
|------|------|------|
| Hermes 写 ops/research | 机制 B：`hindsight-bank` 脚本（Python SDK 封装，`retain --bank ops "..."`） | 半天，脚本放 my-scripts/ |
| Hermes 读 ops/research/开发域 | 机制 C：`hindsight-bank recall --bank <id> "..."`，多 bank 可传 `--banks ops,research` 聚合 | 同脚本扩展 |
| Hermes 日常 | 保持 hermes bank 不动 | 现状 |

`hindsight-bank` 脚本定位：**轻量 CLI 封装，不碰 Hermes 代码**（延续"配置驱动优于代码启发式"）。命令：
```
hindsight-bank retain --bank ops "服务器 huipu-22 新增 DM8 容器 15237 端口"
hindsight-bank recall --bank ops "DM8 部署"
hindsight-bank recall --banks ops,research "达梦数据库"
hindsight-bank reflect --bank research "我学过的知识图谱方案对比"
```

---

## 八、防止混乱的防线（V2 增补）

1. **域级隔离**：通用/运维/研究/项目业务线/agent 行为 五类域分开——这是"不混乱"的根基
2. **项目共享 + 来源溯源**：coding-agent::\* 内 pi 和 claude code 共享，但 harness 标记区分"谁记的"
3. **agent 行为独立**：pi bank 与 claude-code bank 不互通——行为模式不混淆
4. **结构化组织**：bank 内部 document → fact → entity 图谱 → observation，检索按相关性召回

---

## 九、实施路线图（V2）

| 优先级 | 行动 | 产出 |
|:------:|------|------|
| P0 | 确认剩余 2 个决策点（见第十节） | 定稿 bank 清单 |
| P1 | `npm i -g hindsight-coding-agents` + install + 配置 mapPathToBank + harness 路由 | claude code 接入，项目集群聚合生效 |
| P2 | 创建 ops/research bank + 写 `hindsight-bank` 脚本 + 运维知识沉淀试点 | Hermes 定向读写共享域 |
| P3 | pi 接入（MCP 或 REST，bank_id 路由：项目→业务线 bank / 个人→pi bank） | pi 开发记忆自动化 |
| P4 | bank 管理规范文档（命名、mission 模板、读写约定） | 规范沉淀 |

---

## 十、剩余 2 个决策点（请确认）

1. **pi 与 claude code 的项目记忆共享粒度**：
   - 方案 A（推荐）：同一业务线 bank 共享——pi 和 claude code 在同一项目（如 yszx）时写同一个 bank，项目连续性最好，harness 标记防混淆
   - 方案 B：完全独立——pi 的项目记忆只进 pi 专属 bank，与 claude code 互不可见（牺牲项目连续性，换取最大隔离）
   - 影响：决定 pi 接入时 bank_id 怎么路由

2. **agent 个人 bank 的建法**：
   - 方案 A（推荐）：先建 `pi` bank（主开发 agent），`claude-code` bank 随 coding-agents 落地时建
   - 方案 B：两个都现在建（提前准备）
   - 影响：仅创建时机，不影响架构
