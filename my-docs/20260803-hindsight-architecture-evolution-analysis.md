# Hindsight 架构演进分析 — 为什么从"分层"走向"bank + fact_type 双维度"

> 生成日期：2026-08-03
> 方法：源码迁移史实证（alembic 迁移链 + git log），非文档推断
> 上游版本：b5d8439c（官方最新）
> 背景：本系列文档此前以"L1/L2/L3 分层"理解 Hindsight，经源码验证确认系统无分层，真实维度为 bank + fact_type。本文深挖演进史，回答"为什么"。

---

## 一、演进时间线（迁移史实证）

### 阶段 0：初始 — memory_units 单表起步

初始 schema（`5a366d414dce_initial_schema.py`）就建立了 `memory_units` 单表 + `fact_type` 字段，类型含 world / experience / opinion / observation。**Hindsight 从第一天起就是单表模型，分层是后来的插曲。**

### 阶段 1：分层尝试 — mental_models 独立表时代

mental_models 被当作"特殊实体"，拥有独立表结构、版本表、历史表、max_tokens、结构化内容，先后经历 15+ 个迁移：

| 迁移 | 内容 |
|------|------|
| `h3c4d5e6f7g8` | mental_models_v4（独立表） |
| `j5e6f7g8h9i0` | mental_model_versions（版本表） |
| `c3d4e5f6g7h8` | 加 history（历史表） |
| `v7q8r9s0t1u2` | 加 max_tokens |
| `b3w4x5y6z7a8` | 加 structured_content |
| `u6p7q8r9s0t1` / `m8h9i0j1k2l3` | id 改 TEXT 类型 |
| `w8r9s0t1u2v3` | 修 PK 隔离 |

特征：**每次字段演进 = 一个独立迁移**。分层方案下，"心智模型"和"事实"被当作两套完全不同的数据结构维护。

### 阶段 2：第一次类型收敛 — opinion 被合并（2026-01-15）

`i4d5e6f7g8h9_delete_opinions.py` 原文：
> "Opinions are no longer a separate fact type - they are now represented through mental model observations with confidence scores."

**opinion 概念上无法与 world 划清边界**（"用户偏好"算 opinion 还是 world？），判别成本高，被合并进 observation。这是"类型必须互斥可判"原则的第一次实践。

### 阶段 3：分层峰值与急转 — 同一天内试错收敛（2026-01-21）

**同一天三个迁移**，完整呈现"尝试 → 验证 → 否定 → 合并"闭环：

```
n9i0j1k2l3m4  创建 learnings 表（自动归纳）+ pinned_reflections（用户精选）
o0j1k2l3m4n5  迁移 mental_models 数据进 learnings/pinned_reflections
p1k2l3m4n5o6  DROP learnings、DROP mental_models，合并进 memory_units！
```

`p1k2l3m4n5o6_new_knowledge_architecture.py` 设计注释（原文）：
> "The new architecture:
> - Directives: Hard rules in their own table
> - **Mental Models: Stored in memory_units with fact_type='mental_model'**
> - Reflections: User-curated documents (renamed from pinned_reflections)"

合并方式极简：`memory_units` 加三列 `proof_count`（支持该认知的事实数）、`source_memory_ids`（归纳来源数组）、`history`（JSONB 变更历史），加一个部分索引 `idx_memory_units_mental_models (bank_id, fact_type) WHERE fact_type='mental_model'`。**learnings 表存活不到一天。**

### 阶段 4：术语重命名 — 概念澄清（2026-01-26）

`t5o6p7q8r9s0_rename_mental_models_to_observations.py`：
> "Observations: Consolidated knowledge synthesized from facts (was mental_model)
> Mental Models: Stored reflect responses (was reflections)"

术语反转：**observation** = 从事实归纳的观测（事实的升华），**mental model** 改指 reflect 推理产物。概念边界最终清晰。

### 阶段 5：平级架构成熟（2026-02 至今）

- observation 持续演进，全部基于单表：search_vector 回填、orphan 清扫×2、tags 并入 memory_units、observation_sources 表
- 2026-04-02 彻底清理 opinion 残留（drop confidence_score 列）→ **类型最终收敛为 world / experience / observation 三个**
- 新能力建立在平级之上：`reversible curation`（edit/invalidate/revert）、`knowledge pages`（client-managed）、`pluggable memories storage backend`

---

## 二、为什么从分层到平级（深度分析）

### 1. 统一生命周期与 curation（操作一致性）

`de22b606 feat(memory): reversible curation` — 编辑/作废/恢复对任何记忆类型走同一条链路。

分层时代：事实和心智模型的生命周期不同步——编辑一个 fact 与编辑一个 mental model 是两套 CRUD 逻辑，invalidate 一个 mental model 还要处理它依赖的 facts。**每多一层，操作面就多一倍。**

平级后：一条 curation 链路处理所有类型，`edit/invalidate/revert` 天然一致。

### 2. 统一检索与统一排序（语义连续性）

当前实现（`retrieval.py:182`）：
> "Uses UNION ALL of per-fact_type subqueries so that each arm has its own ORDER BY ... LIMIT, enabling the partial HNSW indexes per fact_type"

即：**存储合一、索引分区、查询合一**——
- 存储：单表
- 索引：按 fact_type 的部分 HNSW 索引（`idx_mu_emb_world` / `idx_mu_emb_experience` / `idx_mu_emb_observation`），类型特定优化不丢失
- 查询：UNION ALL 合并各类型结果 + 统一 reranker 排序

结果是 recall 天然返回"事实 + 认知"混合列表，按相关性统一排序。分层时代 fact 检索和 mental model 检索分开，需要额外的融合逻辑（RRF 等），语义连续性被打断——**用户问一个问题，系统要分两次想**。

### 3. 索引体系单一化（运维成本）

分层时每层独立表 = 每层独立 embedding 列、独立 search_vector、独立 BM25 索引、独立向量索引。一次字段演进 = 一个迁移（mental_models 的 15+ 迁移就是证据）。

平级后：加列一次 ALTER 解决（如 observation tags 直接 `z1u2v3w4x5y6_add_observation_tags_to_memory_units`）。**单表的迁移成本是 O(1)，分层是 O(层数)。**

### 4. 概念连续性（认知本质）

world / experience / observation 是**同一连续谱**：事实（低抽象）→ 观测（高抽象），本质都是"记忆单元"。结构高度同构——都是 text + 时间 + 实体 + 标签，差异只是 `proof_count` / `source_memory_ids` 这类**溯源字段**。

分层强制割裂：把"心智模型"当成另一类东西，独立 schema、独立 CRUD、独立查询。但 LLM 归纳产物与原始事实在存储结构上几乎一样——**为 3 个溯源字段建一个表，是过度设计**。

### 5. 类型收敛的自我修正（opinion 教训）

| 事件 | 决策 | 原则 |
|------|------|------|
| opinion 删除（2026-01-15） | 并入 observation | 与 world 边界不清，判别成本高 |
| mental_model 并入单表（2026-01-21） | fact_type='mental_model' | 结构同构，不需独立表 |
| mental_model → observation 改名（2026-01-26） | 术语澄清 | 概念边界必须可教 |
| opinion 残留清理（2026-04-02） | drop 专用列 | 不留死类型 |

收敛原则：**类型必须"互斥可判"，否则就合并**。最终 3 类型——world（客观）/ experience（行为）/ observation（归纳）——判别清晰，无重叠。

### 6. 可插拔后端（未来演进）

`b769045b feat(engine): pluggable memories storage backend (#2917)` — 存储后端可替换。

分层架构下，每个后端都要实现 N 层结构（facts 表 + mental models 表 + learnings 表 + reflections 表），换后端成本爆炸。平级架构下，后端只需实现"一个 memory_units 语义"——**单表是后端可插拔的前提**。

### 7. bank 隔离的正交性

隔离维度（bank）与类型维度（fact_type）**正交**：bank × type 任意组合都成立（bank A 的 world、bank A 的 observation、bank B 的 world...）。

分层时代隔离与类型耦合：每层表都挂 bank_id 且独立管理——mental model 的隔离和 fact 的隔离是两套体系，删除一个 bank 要级联 N 层。平级后 `bank_id` 是唯一外键维度，**隔离逻辑单一，级联删除一次完成**。

### 8. 遗留的例外：directives 为什么保留独立表？

唯一存活的分层是 `directives`（硬规则表）。为什么它没被合并？

判据：**是否参与"检索-归纳-遗忘"的记忆生命周期**——
- directives 是**规则**不是**记忆**：不可被 consolidation 修改、不参与语义检索（无 embedding 语义）、优先级/激活状态是管理属性
- memory_units 是**记忆**：参与 retain（写入）→ consolidation（归纳）→ recall（检索）→ invalidate（遗忘）完整生命周期

**分层与否的分界线不是"抽象层级"，而是"生命周期是否一致"。** 生命周期一致 → 单表 + 类型字段；生命周期独立 → 独立表。这是整个演进给我们的最终设计准则。

---

## 三、对使用者的启示

1. **用 bank 隔离域，用 fact_type 区分类型**——系统只有这两个维度，不要自己发明"分层"
2. **类型设计遵循"互斥可判"**——opinion 的教训：边界不清的类型不如合并
3. **判断是否独立存储看生命周期**——参与"检索-归纳-遗忘"的进 memory_units；规则/配置类（如 directives）才独立表
4. **单表平级 + 部分索引是通用模式**——存储合一、索引分区、查询合一，兼顾统一性与类型感知优化

---

## 四、关键源码位置速查

| 关注点 | 位置 |
|--------|------|
| 分层→平级转折迁移（DROP learnings/mental_models） | `alembic/versions/p1k2l3m4n5o6_new_knowledge_architecture.py` |
| 术语重命名（mental_model→observation） | `alembic/versions/t5o6p7q8r9s0_rename_mental_models_to_observations.py` |
| opinion 合并（第一次类型收敛） | `alembic/versions/i4d5e6f7g8h9_delete_opinions.py` |
| opinion 残留清理（最终收敛 3 类型） | `alembic/versions/g2h3i4j5k6l7_remove_opinion_fact_type.py` |
| 当前 fact_type 枚举（权威） | `engine/response_models.py:13` — world/experience/observation |
| 单表统一检索（UNION ALL per-fact_type） | `engine/search/retrieval.py:182-196` |
| consolidation 写 observation（同表） | `engine/consolidation/consolidator.py:978,2290` |
| MemoryUnit 模型（无 level/layer 字段） | `engine/memories/base.py:123-143` |
| 可插拔存储后端 | commit `b769045b`（#2917） |
| knowledge pages（平级上的新能力） | `alembic/versions/a9b8c7d6e5f4_add_knowledge_pages.py` |
