# Hindsight 本地 Docker 部署记录

| 字段 | 值 |
|------|-----|
| 部署日期 | 2026-07-07 |
| 版本 | `hindsight-local:v0.8.6-wkj`（官方 v0.8.6 + 本地源码覆盖，alembic head a9b8c7d6e5f4） |
| 分支 | `wkj-dev` |
| 上游 | `github.com/vectorize-io/hindsight` |

---

## 一、部署架构

```
┌───────────────────────────────────────────────────────┐
│  Docker 宿主机 (macOS Apple Silicon)                    │
│                                                        │
│  ┌─────────────────────────────┐  ┌──────────────────┐ │
│  │  hindsight-app (hindsight)  │  │  hindsight-db    │ │
│  │  ┌───────────────────────┐  │  │  pgvector:pg18   │ │
│  │  │  API (FastAPI) :8888  │  │  │  PostgreSQL 18   │ │
│  │  │  CP (Next.js) :9999   │  │  │  + pgvector      │ │
│  │  └───────┬───────────────┘  │  └────────┬─────────┘ │
│  │          │                  │           │           │
│  │          │ MiniMax API      │           │ localhost │
│  │          ▼                  │           ▼           │
│  │  api.minimaxi.com/v1       │  docker/vols/        │
│  │  model: MiniMax-M2.7       │  hindsight/pg_data/   │
│  │                            │                       │
│  │  Ollama (宿主机)            │                       │
│  │  host.docker.internal:11434│                       │
│  │  model: bge-m3             │                       │
│  └─────────────────────────────┘  └──────────────────┘ │
└───────────────────────────────────────────────────────┘
```

### 组件清单

| 容器 | 镜像 | 端口 | 用途 |
|------|------|------|------|
| `hindsight-app` | `hindsight-local:v0.8.6-wkj` | 8888/9999 | API + 控制面板 |
| `hindsight-db` | `pgvector/pgvector:pg18` | 5432（容器内） | PostgreSQL + pgvector |

### 外部依赖

| 依赖 | 端点 | 用途 |
|------|------|------|
| MiniMax M2.7 | `https://api.minimaxi.com/v1` | LLM 推理（记忆提取/反思） |
| Ollama bge-m3 | `http://host.docker.internal:11434/v1` | Embeddings（1024 维中文向量） |

---

## 二、配置结构

```
my-agent-group/docker/                       # 部署统一管理（代码目录不存映射数据）
├── compose/hindsight/                       # Docker 部署配置
│   ├── docker-compose.yaml                  # 主 Compose 文件（project name: hindsight）
│   ├── .env                                 # 密钥（.gitignore 排除）
│   ├── .env.example                         # 环境变量模板
│   ├── KEYS.md                              # 密钥说明文档
│   └── start.sh                             # 一键启动脚本
└── vols/hindsight/pg_data/                  # 持久化数据（.gitignore 排除）
                                             # PostgreSQL 数据库文件（bind mount）

代码管理: my-agent-group/projects/memory/hindsight/（wkj-dev 分支）
项目文档: my-docs/（部署分析 + 部署状态 + 架构演进分析等）
```

### 关键配置说明

**LLM（MiniMax M2.7）**：
- Hindsight 源码中 `minimax` provider 写死了 `api.minimax.io`（缺字母 i）
- 绕过方式：使用 `openai` provider + 自定义 `HINDSIGHT_API_LLM_BASE_URL=https://api.minimaxi.com/v1`
- 模型：`MiniMax-M2.7`，Key 格式 `sk-cp-...`

**Embeddings（Ollama bge-m3）**：
- 通过 `openai` embeddings provider 对接宿主机 Ollama
- Docker Desktop macOS 环境下 `host.docker.internal` 自动解析到宿主机
- bge-m3 模型 1024 维，中文最优

**数据持久化**：
- 使用 bind mount `docker/vols/hindsight/pg_data/`（绝对路径）而非 Docker named volume
- `docker compose down -v` 不会删数据
- 重建容器时数据完整保留

---

## 三、关键验证记录

### 启动日志

```bash
$ cd docker/compose/hindsight && docker compose up -d
Container hindsight-db Starting
Container hindsight-db Started
Container hindsight-db Healthy
Container hindsight-app Starting
Container hindsight-app Started
```

### API 健康检查

```json
// GET /health
{"status": "healthy", "database": "connected"}
```

### Retain 测试（记忆存储）

```json
// POST /v1/default/banks/test-bank/memories
// {"items":[{"content":"Alice works at Google as a senior software engineer..."}]}
{
  "success": true,
  "bank_id": "test-bank",
  "items_count": 1,
  "usage": {
    "input_tokens": 2801,
    "output_tokens": 364,
    "total_tokens": 3165
  }
}
```

### Recall 测试（记忆检索）

```json
// POST /v1/default/banks/test-bank/memories/recall
// {"query":"Who works at Google?","limit":3}
{
  "results": [{
    "text": "Alice works at Google as a senior software engineer... | Involving: Alice",
    "type": "world",
    "entities": ["Alice","machine learning","senior software engineer","Google"],
    "scores": {
      "final": 1.099,
      "reranker": 0.999,
      "semantic": 0.641,
      "keyword": 0.300
    }
  }]
}
```

### Ollama bge-m3 嵌入验证

```json
// POST http://localhost:11434/v1/embeddings
// {"model":"bge-m3", "input":"hello world"}
{"dim": 1024, "model": "bge-m3"}
```

### MiniMax API Key 验证

```bash
curl https://api.minimaxi.com/v1/chat/completions → HTTP 200
```

---

## 四、日常运维

### 启动/停止

```bash
cd /Users/weikejia/CODE/my-agent-group/docker/compose/hindsight

# 启动
docker compose up -d

# 停止（保留数据）
docker compose stop

# 停止并删除容器
docker compose down

# 查看日志
docker compose logs -f
docker compose logs -f hindsight-app   # 只看 API
docker compose logs -f hindsight-db    # 只看数据库
```

### 数据备份

数据目录：`/Users/weikejia/CODE/my-agent-group/docker/vols/hindsight/pg_data/`（bind mount，可直接备份）

```bash
# 安全备份（先停止数据库写操作）
docker compose stop hindsight-db
cp -a /Users/weikejia/CODE/my-agent-group/docker/vols/hindsight/pg_data/ /backup/hindsight-pg-$(date +%Y%m%d)/
docker compose start hindsight-db
```

### 更新

```bash
# 拉取新镜像
docker compose pull

# 重建容器
docker compose up -d --force-recreate
```

---

## 五、已知问题与注意事项

1. **MiniMax base URL**：Hindsight 上游代码 `openai_compatible_llm.py:488` 写死 `api.minimax.io`（少 i），必须用 `openai` provider + 自定义 base_url 绕过
2. **Docker named volume 风险**：已改为 bind mount，但若手动执行 `docker compose down -v` 仍有风险（当前无 named volume，-v 无害）
3. **macOS Docker 无 GPU**：Docker Desktop macOS 无法透传 GPU 给 Linux 容器，本地 LLM 方案只能在宿主机跑
4. **首次启动耗时**：镜像 ~520MB，Pull + 数据库迁移 + ML 模型预下载约 2-3 分钟

---

## 六、20260819 追加 — 完整可复现部署流程与要点

> 本节是**可复现部署手册**：给出从零构建镜像、Compose 配置、启动验证、升级、备份的完整步骤与确定性要点。记录时库状态：`wkj-dev` HEAD `11a2020e3`（已并入官方 v0.9.x 主线）。

### 6.1 原料与前置（Reproducible Inputs）

| 原料 | 位置 | 说明 |
|------|------|------|
| 源码/镜像上下文 | `my-agent-group/projects/memory/hindsight`（wkj-dev） | 镜像自编译来源；记录时已同步 v0.9.x 官方主线 |
| 镜像配方 | 仓库 `docker/standalone/Dockerfile` | 官方 standalone 构建配方：将 `hindsight_api/hindsight_api`、`hindsight-control-plane` 等**源码 COPY 进容器**，uv sync + npm build |
| 部署配置 | `my-agent-group/docker/compose/hindsight/`（`docker-compose.yaml`、`.env`、`.env.example`、`KEYS.md`、`start.sh`） | 代码目录不存映射数据，部署统管于根 docker/ |
| 数据卷 | `docker/vols/hindsight/pg_data/`（bind mount） | PostgreSQL 持久化，容器重建不丢数据 |
| 外部依赖 | MiniMax M2.7（`sk-cp-…` Key）+ 宿主机 Ollama（`bge-m3`） | LLM / Embeddings |
| 宿主环境 | macOS Docker Desktop（Apple Silicon） | pgvector 官方镜像有 arm64 支持 |

前置检查：`OLLAMA` 已运行且 `bge-m3` 已拉取；`.env` 已填 `MINIMAX_API_KEY` 与 `HINDSIGHT_DB_PASSWORD`。

### 6.2 镜像构建（自编译，步骤确定）

```bash
# 在仓库根目录，以仓库为 build context（配方位置 docker/standalone/Dockerfile）
cd /Users/weikejia/CODE/my-agent-group/projects/memory/hindsight
# 首次 v0.8.6-wkj（当时基线）或升级 v0.9.x-wkj（当前）：
docker build \
  -f docker/standalone/Dockerfile \
  --build-arg INCLUDE_LOCAL_MODELS=false \
  --build-arg PRELOAD_ML_MODELS=false \
  -t hindsight-local:v0.9.x-wkj .
```

要点：
- 配方会将 `hindsight_api` 等源码直接 COPY 进容器（镜像史已实查：`COPY hindsight-api-slim/hindsight_api /app/…`）。这就是“把我们的源码复制到容器即升级”的机制。
- `INCLUDE_LOCAL_MODELS=false`：因外用 Ollama bge-m3 + MiniMax，不打包本地 ML（节省 ~2GB 并提速）。
- `PRELOAD_ML_MODELS=false`：配合外用嵌入跳过 HF 预下载。
- 产出 API(`8888`)+CP(`9999`) 双服务 standalone 镜像；验证 `docker history` 可见 EXPOSE 8888/9999、`CMD start-all.sh`、`HINDSIGHT_ENABLE_CP=…`。

### 6.3 Compose 配置（现役，完整粘贴要点）

服务 `db`：
- `pgvector/pgvector:pg18`，容器 `hindsight-db`；`POSTGRES_USER=hindsight_user`、`POSTGRES_DB=hindsight_db`、密码来自 `HINDSIGHT_DB_PASSWORD`；
- bind mount `docker/vols/hindsight/pg_data:/var/lib/postgresql/18/docker`；healthcheck `pg_isready`；

服务 `hindsight`（API+CP）：
- 镜像 `hindsight-local:v0.9.x-wkj`（升级后 tag；当前运行 `v0.8.6-wkj`），容器 `hindsight-app`；端口 `8888`/`9999`；
- `HINDSIGHT_API_LLM_PROVIDER=openai`、`HINDSIGHT_API_LLM_BASE_URL=https://api.minimaxi.com/v1`、`HINDSIGHT_API_LLM_MODEL=MiniMax-M2.7`（绕开上游 minimax provider 写死 `api.minimax.io` 缺 i）；
- `HINDSIGHT_API_EMBEDDINGS_PROVIDER=openai`、`HINDSIGHT_API_EMBEDDINGS_OPENAI_BASE_URL=http://host.docker.internal:11434/v1`、`HINDSIGHT_API_EMBEDDINGS_OPENAI_MODEL=bge-m3`（宿主机 Ollama）；
- **`HINDSIGHT_API_RERANKER_PROVIDER=rrf`**（新版默认 reranker 为 local，但 `INCLUDE_LOCAL_MODELS=false` 未打包 sentence-transformers 且无 TEI；新版**不支持 none**，用 `rrf` 纯算法融合实现无模型重排序）；
- **LLM 稳定性调优（20260819 实际应用）**：因 MiniMax M2.7 生成慢（30-60 token/s）且大输出多，调高超时+降并发——
  - `HINDSIGHT_API_LLM_TIMEOUT: 600`（120s->600s，容纳 reflect/consolidation 的大输出）
  - `HINDSIGHT_API_WORKER_MAX_SLOTS: 3`（10->3，降低并发排队，避免互相拖到超时）
  - `HINDSIGHT_API_MENTAL_MODEL_REFRESH_CONCURRENCY: 2`（8->2，缓解 mental-model 刷新抢 LLM）
- `HINDSIGHT_API_DATABASE_URL=postgresql://hindsight_user:${HINDSIGHT_DB_PASSWORD}@db:5432/hindsight_db`；
- `HINDSIGHT_API_HOST=0.0.0.0`、`HINDSIGHT_API_PORT=8888`、`LOG_LEVEL=info`、`WORKER_ID=hindsight-app`（重建后遗留任务可恢复）；
- `HINDSIGHT_CP_DATAPLANE_API_URL=http://localhost:8888`；
- `HF_ENDPOINT=https://hf-mirror.com`、`TRANSFORMERS_VERBOSITY=error`、`HF_HUB_VERBOSITY=error`、`TOKENIZERS_PARALLELISM=false`；
- `depends_on db: condition: service_healthy`；网络 `hindsight-net`（bridge）。

### 6.4 启动与验证（可随意复现）

```bash
cd /Users/weikejia/CODE/my-agent-group/docker/compose/hindsight
./start.sh   # 或 docker compose up -d
```

验证：
```bash
curl -sf http://localhost:8888/health      # {"status":"healthy","database":"connected"}
curl -sf http://localhost:9999             # 控制面板可达
# MiniMax LLM
curl -sf https://api.minimaxi.com/v1/chat/completions -H "Authorization: Bearer $MINIMAX_API_KEY" → HTTP 200
# Ollama bge-m3 嵌入
curl -sf http://localhost:11434/v1/embeddings   → dim=1024, model=bge-m3
# Retain/Recall 抽测（见 20260803 记录示例）
```

日志：`docker compose logs -f` / `logs -f hindsight-app` / `logs -f hindsight-db`。

### 6.5 数据库迁移机制与版本基线

- API 初始化自动执行 Alembic（日志 `Running database migrations…`，含 tenant schema fan-out）。
- 迁移版本统计：仓库 **99 个版本 / 唯一单 head `f2a7c9d4b168`**。
- 升级时从现网 `a9b8c7d6e5f4` → 新 head 的 **8 步线性闭链**（`e4a7c1b9d2f6`→`f2a6d8c4b1e9`→`b3e8d1c6f4a9`→`d9c1a7b4e2f6`→`c4f7a91b2d38`→`e7c3a91f4b62`→`c8b4e2a71f95`→`f2a7c9d4b168`），无分叉、脚本带幂等守卫。
- 手动选项：`hindsight-admin run-db-migration`（可加 `--skip-extension-reconcile`）。

### 6.6 升级流程（v0.8.6-wkj → v0.9.x-wkj）

```bash
# 1) 备份数据库
cd /Users/weikejia/CODE/my-agent-group/docker/compose/hindsight
docker compose stop hindsight-db
docker exec hindsight-db bash -c "pg_dump -U hindsight_user -d hindsight_db" \
  > /Users/weikejia/CODE/my-agent-group/docker/vols/hindsight/backup-$(date +%Y%m%d).sql
docker compose start hindsight-db

# 2) （可选）先用新镜像手动跑迁移验证
# 3) 重建镜像（见 6.2）后改 compose image: 为 hindsight-local:v0.9.x-wkj
# 4) 重建与启动
./start.sh    # 或 docker compose up -d --force-recreate hindsight
# 5) 验证：/health + retain/recall 复验（重点 MiniMax M2.7 经 openai compat 的 function-calling）
```

升级后同步更新 `docker/compose/hindsight/KEYS.md`（版本、99 迁移计数）与 `.env.example`。

### 6.7 要点（稳定可靠的关键）

1. **镜像必须是自编译**：升级 = 以当前 wkj-dev 源码重跑 `docker build`（配方固定），不要手工改运行中容器。
2. **数据只用 bind mount**：`docker/vols/hindsight/pg_data`；严禁 `docker compose down -v`（当前无 named volume，-v 无害但谨记）。
3. **MiniMax 端点**：因上游硬编码 `api.minimax.io`（缺 i），一律用 `openai` provider + `base_url=https://api.minimaxi.com/v1`。
4. **worker ID 固定** `hindsight-app`：容器重建后遗留 processing 任务能恢复。
5. **macOS Docker 无 GPU 透传**：本地 LLM 只能在宿主机（本部署无本地 LLM）。
6. **迁移是闭链可自动**：新镜像首启自动升到 `f2a7c9d4b168`；生产更稳妥是先手动 `run-db-migration` 再切换。
7. **升级前置备份**：任何镜像/迁移操作前先 `pg_dump`。
8. **复现锁定**：代码锁定 `wkj-dev` 记录时 commit，镜像 tag、compose、`.env`、build args 一致即可任意复现。
9. **Reranker 必须 `rrf`**：新版 config 默认 `local`，但 `INCLUDE_LOCAL_MODELS=false` 未打包本地 ML；`none` 不被支持（cross_encoder 会抛 ValueError）。无本地/无 TEI 时必须设 `HINDSIGHT_API_RERANKER_PROVIDER=rrf`。
10. **MiniMax LLM 稳定性调优**：MiniMax M2.7 生成仅 30-60 token/s；短请求 ~1s、大输出（3-4k token）需 23-70s。`HINDSIGHT_API_LLM_TIMEOUT=600`（防大输出超时）、`HINDSIGHT_API_WORKER_MAX_SLOTS=3`、`HINDSIGHT_API_MENTAL_MODEL_REFRESH_CONCURRENCY=2`（防并发排队）。reflect（深度记忆）单次 50-90s 属正常范围（多轮 agent 循环 + 长 final 回答，受生成速度硬约束）；如需提速可设 `HINDSIGHT_API_REFLECT_MAX_COMPLETION_TOKENS` 等（会牺牲深度/篇幅）。

---

## 七、20260819 追加 — 与既有记录的关系

- 本节续于 `20260707-hindsight-deployment-status.md`（首次部署记录，2026-07-07）。
- 配套：`my-docs/20260707-hindsight-docker-deploy-analysis.md`（部署分析）、`my-docs/11-分析报告/20260819-002-hindsight-docker-direct-upgrade-evaluation.md`（升级评估）。
- 升级落地时的“官方 v0.8.6 + 本地源码覆盖”表述即指：**官方 standalone 配方 + wkj-dev 源码内容的自编译镜像**。
