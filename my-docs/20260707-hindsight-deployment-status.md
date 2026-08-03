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
