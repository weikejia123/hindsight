# Hindsight 模型查询失败降级（LLM failover / fallback）能力分析

- 内部版本: V1-20260819
- 状态: 分析报告（基于 wkj-dev 合并的 v0.9.x 源码实查）

> 结论：**支持**。Hindsight 提供三层失败缓解能力——① 单 provider 内置重试；② **Multi-LLM 链（failover / round-robin）**跨模型降级；③ **LiteLLM Router** 跨部署降级。以下逐层说明设置方式、触发边界与限制。

---

## 1. 三层机制总览

| 层 | 机制 | 触发 | 覆盖路径 |
|---|---|---|---|
| ① | 单 provider 内部重试（LLM_MAX_RETRIES） | 网络错误 / 5xx / 限流(429) / 超时 | 所有 LLM 调用 |
| ② | Multi-LLM 链（`HINDSIGHT_API_LLM_<n>_*` + STRATEGY） | 某成员耗尽自身重试后抛 `Exception` | **交互式** `call` / `call_with_tools` |
| ③ | LiteLLM Router（`provider=litellmrouter` + CONFIG） | 暂态错误（5xx / 限流 / 超时）按序降级 | 走 litellmrouter provider 的调用 |

---

## 2. 层①：单 provider 内置重试

默认：`HINDSIGHT_API_LLM_MAX_RETRIES=3`，指数退避 `INITIAL_BACKOFF=1s` → `MAX_BACKOFF=60s`。
（之前日志里的 `attempt=1/4` 即 1 次 + 3 次重试。）

可调：`HINDSIGHT_API_LLM_MAX_RETRIES` / `HINDSIGHT_API_LLM_INITIAL_BACKOFF` / `HINDSIGHT_API_LLM_MAX_BACKOFF`。

**局限**：只对同一模型/同一端点重试，不能解决"该模型/端点本身不可用或配额耗尽"的场景——这种情况需要层②③。

---

## 3. 层②：Multi-LLM 链（跨模型降级，推荐）

### 3.1 结构
- **member 0 = primary**：未索引的 `HINDSIGHT_API_LLM_PROVIDER`（即现有主模型）。
- **member 1..N = 备用**：`HINDSIGHT_API_LLM_<n>_PROVIDER`（索引必须从 1 连续，遇到第一个未设置的 `_PROVIDER` 即停止扫描）。
- 每个成员自己保留**独立的重试预算**，只有**耗尽自身重试并抛出**后，才切到下一个成员。

### 3.2 策略（`HINDSIGHT_API_LLM_STRATEGY`，JSON）
```json
{"mode": "failover"}                     // 按成员顺序 [0..N] 试，主失败→备
{"mode": "round-robin", "weights": [3,1]} // 轮转起始成员（可加权），出错后落到后续
```
- `failover`：每请求都从 primary 开始，primary 失败才切备用。
- `round-robin`：每请求轮换起始成员（`weights` 仅此模式有效，正整数，数量须与成员数一致）。

### 3.3 成员可配置字段（`HINDSIGHT_API_LLM_<n>_*`）
`PROVIDER`、`API_KEY`（requires_api_key 的 provider 必填）、`MODEL`、`BASE_URL`、`REASONING_EFFORT`、`EXTRA_BODY`、`DEFAULT_HEADERS`、`CACHE_AFFINITY`、`GEMINI_SERVICE_TIER`/`BEDROCK_SERVICE_TIER`、`VERTEXAI_PROJECT_ID/REGION/SERVICE_ACCOUNT_KEY`、`LITELLMROUTER_CONFIG`。

### 3.4 docker-compose 示例（MiniMax 主 + 备用 openai-compatible）
```yaml
HINDSIGHT_API_LLM_PROVIDER: openai
HINDSIGHT_API_LLM_BASE_URL: https://api.minimaxi.com/v1
HINDSIGHT_API_LLM_MODEL: MiniMax-M2.7
HINDSIGHT_API_LLM_API_KEY: ${MINIMAX_API_KEY}

HINDSIGHT_API_LLM_1_PROVIDER: openai
HINDSIGHT_API_LLM_1_BASE_URL: https://api.another.com/v1
HINDSIGHT_API_LLM_1_MODEL: some-fallback-model
HINDSIGHT_API_LLM_1_API_KEY: ${FALLBACK_KEY}

HINDSIGHT_API_LLM_STRATEGY: '{"mode":"failover"}'
```

### 3.5 每操作独立覆盖
可用专用链覆盖全局：
- `HINDSIGHT_API_RETAIN_LLM_<n>_*` + `HINDSIGHT_API_RETAIN_LLM_STRATEGY`
- `HINDSIGHT_API_REFLECT_LLM_<n>_*` + `HINDSIGHT_API_REFLECT_LLM_STRATEGY`
- `HINDSIGHT_API_CONSOLIDATION_LLM_<n>_*` + `HINDSIGHT_API_CONSOLIDATION_LLM_STRATEGY`

---

## 4. 层③：LiteLLM Router（部署级） 

- `HINDSIGHT_API_LLM_PROVIDER=litellmrouter`
- `HINDSIGHT_API_LLM_LITELLMROUTER_CONFIG`（JSON：每个 entry 是一个 deployment）
- Router 按声明顺序尝试各 deployment，遇暂态错误（5xx / 限流 / 超时）自动 fallback 到下一个。
- 适合"同一 provider、多 key / 多 endpoint"的负载与容灾；与层②（按模型）互补。

---

## 5. 触发边界（`engine/multi_llm.py::_should_failover`）

**会触发降级**（`isinstance(exc, Exception)`）：网络错误、provider 5xx、限流(429)、超时——在成员自身重试耗尽后切下一个。

**不会触发降级**：
- `OutputTooLongError`（超长输出）——换一个模型/端点同样装不下，直接透传。
- `CancelledError` / `KeyboardInterrupt` / `SystemExit`（`BaseException`，非 `Exception`）——直接透传，不降级。

---

## 6. 边界与限制（务必注意）

1. **batch retain 与直接 `_provider_impl` 访问只走 primary**（属性透传），**failover/round-robin 不适用**于批处理路径——只有交互式 `call` / `call_with_tools` 能跨成员降级。
2. **启动验证不对称**：primary 硬验证（不可达会趁 start 警告/暴露）；备用成员**软验证**（不可达仅 warning，不阻塞启动，留待请求时再试）——因此备用模型配置错误可能到"真需要时"才发现。
3. **配置错误 fail-fast**：STRATEGY JSON 非法、`mode` 不对、`weights` 用于非 round-robin、weights 数量与成员数不符、requires_api_key 的成员缺 key、无成员等，都会在**启动时报 `ValueError`**，绝不静默降级。
4. **索引必须连续**：`LLM_1` 之后遇到未设置的 `LLM_<n>_PROVIDER` 即停止，不能出现空洞。
5. **每成员一次请求只成功即返回**；全部成员失败后抛出**最后一个成员的错误**。
6. 降级会**显著增加请求延迟**（每次切换都含前序成员的重试+退避），适合"可用性优先"，不适合低延迟场景。

---

## 7. 与我们当前部署的关系

- 当前 compose **只配置了单 provider**（openai / MiniMax M2.7），**未配任一备用成员、未配 STRATEGY、未用 litellmrouter** → 现在只有**层①内置重试**（attempt 1/4），**没有跨模型降级**。
- 之前遭遇的 `429 Token Plan 用量上限`（配额耗尽）正属于"该端点不可用/限流"，单靠重试无法解决；配一个备用模型 + `failover` 策略可自动切走，显著提升可用性。
- 若配置备用，建议至少一个是**与 MiniMax 不同的独立端点**，才能真正规避"单一提供商配额/故障"。

---

## 8. 相关：reranker / embeddings 的类似能力（供参考）

- reranker 也有 failover 链（`RerankerMemberConfig`），与 LLM 同理；当前部署用 `HINDSIGHT_API_RERANKER_PROVIDER=rrf`（无模型），无降级对象。
- embeddings 无跨 provider 自动降级链（配置 openai 即固定走该端点）。

---

## 9. 结论

Hindsight v0.9.x **支持模型查询失败后的跨模型降级**：单点用重试，多模型用 `Multi-LLM failover/round-robin`，多部署用 `LiteLLM Router`。要真正提升"MiniMax 不可用/配额耗尽"时的可用性，应在 compose 增加**备用 provider 成员 + `LLM_STRATEGY='{"mode":"failover"}'`**，并留意 batch-retain 不走 failover 这一关键限制。
