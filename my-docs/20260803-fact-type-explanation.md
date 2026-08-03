# 世界事实、经历、观察：三种记忆类型的源码级解释

> 版本: v0.8.6-wkj / alembic a9b8c7d6e5f4 / 2026-08-03
> 视角: 用户视角（回答"我的 hindsight 理解很浅薄"的读者）
> 方法: 全部结论来自源码实查（hindsight-api-slim/hindsight_api/），不是文档转述

---

## 零、一句话回答

- **世界事实（world）** = 关于世界/用户/他人"是什么样"的客观事实 —— 主语是**世界**。
- **经历（experience）** = 助手/agent"做过什么"的第一人称经历 —— 主语是**我（助手）**。
- **观察（observation）** = 系统后台从多条事实中**归纳出来的规律/状态**，带证据可追溯 —— 它不是直接存进去的，是"想出来的"。

三者的核心区别只有两个维度：**谁做的**（用户世界 vs 助手），**怎么来的**（直接记录 vs 归纳合成）。

---

## 一、它们在代码里怎么定义（权威来源）

### 1. 合法类型的枚举

`engine/response_models.py:13`

```python
VALID_RECALL_FACT_TYPES = frozenset(["world", "experience", "observation"])
```

系统只认这三种。注意：**这里没有 L1/L2/L3 分层**——三种类型存在同一张 `memory_units` 表里，靠 `fact_type` 字段区分，不是三个存储层。

### 2. retain（存）阶段：LLM 只输出两种类型

`engine/retain/fact_extraction.py:714-716`（CLASSIFICATION 规则，这就是 LLM 判定边界的依据）：

```
fact_type:
- "world": Objective/external facts, including the user's preferences, rules,
  corrections, constraints, plans, traits, or context. These stay "world" even
  when the user states them during an assistant interaction
  (e.g., "User prefers browser_navigate over web_search",
   "User corrected the project deadline").
- "assistant": Actions, experiences, or observations the assistant/agent
  actually performed (e.g., "I changed X", "I discovered Y", "I debugged Z").
  Use this for the assistant/agent doing, trying, learning, deciding,
  recommending, or responding — not merely for user facts mentioned in conversation.
```

**关键发现 1**：LLM 输出的原始类型是 `world` / `assistant`（说话者视角），**没有** `experience`。
`experience` 是存储视角的叫法。

### 3. assistant → experience 的机械映射

`engine/retain/fact_extraction.py:1478-1487`：

```python
# Critical field: fact_type — "assistant" maps to "experience", everything else is "world".
raw_fact_type = llm_fact.get("fact_type")
if raw_fact_type == "assistant":
    fact_type = "experience"
elif raw_fact_type == "world":
    fact_type = "world"
else:  # 兜底：用 fact_kind 再判一次
    fact_type = "experience" if raw_fact_kind == "assistant" else "world"
```

**关键发现 2**：边界判定完全交给 LLM（prompt 规则），代码只做机械映射，没有额外校验。
LLM 说 assistant → experience，LLM 说 world → world，其他任何值 → 默认 world。

### 4. observation 不是 retain 提取的

`engine/consolidation/consolidator.py:8`：

```python
"""Observations are stored in memory_units with fact_type='observation' ..."""
```

observation 由 **consolidation（后台升华进程）** 自动生成。consolidation 的 LLM 拿到"一批新事实 + 已有的相关 observation"，决定：
- **CREATE**：没有匹配的已有 observation → 新建
- **UPDATE**：同一 facet 已被现有 observation 覆盖 → 合并证据（attach 新事实 ID）
- **DELETE**：几乎不删（PRESERVE HISTORY 规则）

每个 observation 带三个特殊字段：
| 字段 | 含义 |
|------|------|
| `proof_count` | 支撑它的事实数量（证据强度） |
| `source_memory_ids` | 来源事实的 ID 列表（可追溯） |
| `consolidated_at` | 最近一次归纳时间 |

还有一个算法计算的 `trend`（observations.py:15-30）：根据证据时间戳分布算趋势——
STABLE / STRENGTHENING / WEAKENING / NEW / STALE（如"这个规律最近还在被验证"或"已经过时"）。

---

## 二、边界怎么划（三个判定点）

### 判定点 1：world vs experience —— 由 retain 的 LLM 判定

判定依据（prompt 原文逻辑）：**这个事实的主语是谁？**

| 情形 | 类型 | 为什么 |
|------|------|--------|
| "用户喜欢深色模式" | world | 关于用户的事实 |
| "用户改了我的项目截止日期" | world | **即使用户是在对话中说出来的**，仍是 world |
| "用户说他昨天调试了 Z" | world | 用户在**叙述**自己的经历，不是助手做的 |
| "我（助手）改了 X" | experience | 助手实际执行的动作 |
| "我（助手）发现 Y 有 bug" | experience | 助手做的/发现的 |
| "我（助手）建议用 A 方案" | experience | 助手推荐/决定 |

边界铁律：**experience 只属于 assistant**。用户叙述的任何事情（哪怕是"我调试了 Z"）都判 world，因为那是关于用户的事实。

### 判定点 2：observation 的范围 —— 由 consolidation 的 LLM 判定

`engine/consolidation/prompts.py` PROCESSING RULES 关键几条：

- **一条 observation 一个 facet**：一个计数（"有 3 个 item"）、一个实体（"有条叫 Rex 的狗"）、一段关系（"在 Google 工作"）各成一条，**绝不合并不同 facet**。
- **按实体/facet 匹配，不按主题**："卖掉了 item X" 只更新 X 的 observation，不碰别的。
- **状态变化要更新**："X 死了" → UPDATE 现有 observation 反映当前状态（带日期）。
- **不做算术**："有 2 条狗" + "有条叫 Rex 的狗" ≠ 3 条。不推导、不计算，只归纳已陈述的内容。
- **保留历史**：重要事件（卖了、死了、搬了）永不删除。

### 判定点 3：什么内容值得记 —— retain 的"选择性"规则

`fact_extraction.py` 的 SELECTIVITY 规则（决定事实是否提取，间接影响三类内容的边界）：

- 值得记：个人信息、偏好、重大事件、计划/目标、专长、重要上下文、感官/情绪细节
- 不值得记：寒暄（"你好"）、纯客套（"谢谢""好的"）、过程废话（"让我查一下"）、重复信息

---

## 三、流程：一条记忆从输入到三种类型的完整链路

```
用户/助手对话
   │
   ▼
【1. retain 存】──────────────────────────────────────────────
   输入文本 → LLM 提取（fact_extraction.py）
   ├─ 判定 fact_kind: event（可定时的具体事件）/ conversation（持续状态）
   ├─ 判定 fact_type: world / assistant（LLM 视角）
   └─ 代码映射: assistant → experience（存储视角）
        │
        ▼
   写入 memory_units 表（fact_type = world 或 experience）
        │
        ▼
【2. consolidation 升华】（后台定时，全自动）──────────────────
   取新事实 + 相关旧 observation → LLM 决定 CREATE/UPDATE
        │
        ▼
   写入 memory_units 表（fact_type = observation，
   带 proof_count / source_memory_ids / consolidated_at）
        │
        ▼
【3. recall 查】──────────────────────────────────────────────
   四路检索（语义/BM25/图谱/时间）+ reranker
   三种类型都会被召回；observation 的 source_memory_ids
   允许"溯源"——看到一个观察能展开它的证据事实
```

三个操作作用于**同一张表**，是流程先后关系，不是存储分层。

---

## 四、架构：存储层面如何区分

`engine/memories/base.py` 的 MemoryUnit 模型（memory_units 表）：

```python
unit_id          # 唯一 ID
text             # 事实内容
fact_type        # world | experience | observation  ← 唯一的类型区分维度
proof_count      # 仅 observation 用：支撑事实数
source_memory_ids# 仅 observation 用：来源事实 ID 列表
consolidated_at  # 仅 observation 用：归纳时间
```

- world / experience：proof_count=1，source_memory_ids 空 —— 一条陈述一个事实
- observation：proof_count≥1（通常多条），source_memory_ids 非空 —— 多条陈述归纳成一个规律

**本质**：三种类型 = 同一张表里的三行"态"，靠 fact_type 区分；observation 是"二阶事实"（关于事实的事实），所以多了证据溯源字段。

---

## 五、用户视角的心智模型（怎么理解才不浅薄）

把记忆系统想成一个**记笔记的人 + 定期整理的人**：

1. **world = 剪报**。把关于世界/用户/他人的客观信息剪下来贴墙上（"魏可佳偏好命令行工具"、"项目在 wkj-dev 分支开发"）。这些是"这个世界是什么样"的静态知识。

2. **experience = 工作日志**。把助手自己干过的活记下来（"我部署了 v0.8.6"、"我发现了 DM8 迁移问题"）。这些是"我做过什么"的动态经历。

3. **observation = 月度总结**。整理的人每隔一段时间，把散落的剪报和工作日志归拢，提炼出规律（"该项目似乎总在周三出部署问题"、"用户常用 docker compose 管理服务"）。总结必须能追溯到原材料（引文/来源 ID），防止编造。

一个辅助记忆的口诀：

```
world  = 世界 是 什么样          （第三人称，客观）
experience = 我   做 过 什么      （第一人称，助手）
observation = 规律  正在 变成 什么样（归纳，多证据，带趋势）
```

---

## 六、对使用者的实操建议

1. **想让某条知识被记住 → 用 world 视角描述**。"用户偏好 X"、"项目约定 Y" 这种句式（即使原话是"我改成 Y 了"，描述成关于项目/用户的客观状态更稳）。

2. **想让自己的操作被记住 → experience 自然发生**。retain 输入里包含"我做了 X"的句子，LLM 会自动判 experience。

3. **观察是自动的，不需要手动触发**。consolidation 后台跑，你只需保证**同类事实用一致的说法/实体名**（"Rex" 别一会儿"狗"一会儿"Rex"），归纳质量会更好。

4. **判断一条记忆属于哪类，问两个问题**：
   - 主语是谁？（世界/用户/他人 → world；助手 → experience）
   - 是直接记录还是归纳？（retain 存的 → world/experience；consolidation 生成的 → observation）

5. **边界模糊时**：默认 world（代码兜底逻辑就是"其他一切 → world"）。experience 是窄门（只有 assistant 的动作），observation 是后台产物（你无法直接 retain 一个 observation）。

---

## 附：源码位置速查

| 关注点 | 位置 |
|--------|------|
| 类型枚举（权威） | hindsight-api-slim/hindsight_api/engine/response_models.py:13 |
| LLM 类型判定 prompt | engine/retain/fact_extraction.py:714-716（CLASSIFICATION） |
| assistant→experience 映射 | engine/retain/fact_extraction.py:1478-1487 |
| observation 生成规则 | engine/consolidation/prompts.py（PROCESSING RULES） |
| observation 写库 | engine/consolidation/consolidator.py:978（fact_type="observation"） |
| observation 模型 + trend | engine/reflect/observations.py |
| memory_units 表结构 | engine/memories/base.py:125-143 |
