# Hindsight Docker 直接升级评估（v0.8.6-wkj → v0.9.x 官方主线）

- 内部版本: V1-20260819
- 状态: 分析报告

> 结论先行：**可以**直接升级。程序侧既可以改用官方 ghcr 镜像，也可以从本地 repo 自编译新镜像；数据库结构具备**单 head 线性迁移链**（现网 `a9b8c7d6e5f4` → 新 head `f2a7c9d4b168`），且 8 步新迁移均为幂等安全的 DDL，可由新镜像启动时自动执行。

---

## 1. 当前部署实况

| 项 | 现状 |
|------|------|
| API+CP 容器 | `hindsight-app`，镜像 `hindsight-local:v0.8.6-wkj`，运行 2 周 |
| 数据库容器 | `hindsight-db`，`pgvector/pgvector:pg18`（PostgreSQL 18 + pgvector），healthy |
| DB 用户/库 | `hindsight_user` / `hindsight_db`，bind mount 于 `docker/vols/hindsight/pg_data` |
| LLM | MiniMax M2.7，经由 `openai` provider + `https://api.minimaxi.com/v1` base_url 绕开上游 minimax 硬编码缺陷 |
| Embeddings | Ollama `bge-m3`（宿主机），通过 `openai` compat /v1 endpoint |
| 实际 DB 迁移版本 | `a9b8c7d6e5f4`（实查 `alembic_version`，与 KEYS.md 记载的 91 迁移一致） |

## 2. 新代码版本的数据库迁移面

- 仓库 `hindsight-api-slim/hindsight_api/alembic/versions/` 共 **99 个迁移版本**；AST 解析确认依赖图为**全图唯一单 head：`f2a7c9d4b168`（add_mental_models_cron_index）**。
- 从现网 head `a9b8c7d6e5f4` 到新 head 的 8 步闭链：

| 步骤 | revision | 内容 | 性质 |
|------|---------|------|------|
| 1 | `e4a7c1b9d2f6` | drop_memory_units_access_count | 删列（幂等） |
| 2 | `f2a6d8c4b1e9` | drop_stale_global_memory_units_vector_index | 删索引 |
| 3 | `b3e8d1c6f4a9` | entity_kind_partial_trgm_index | 建 pg_trgm 部分索引（CONCURRENTLY、IF NOT EXISTS；无 pg_trgm 时跳过） |
| 4 | `d9c1a7b4e2f6` | async_operations_serialization_key | 加串行化索引 |
| 5 | `c4f7a91b2d38` | add_entity_maintenance_queue | 新建队列表 |
| 6 | `e7c3a91f4b62` | add_mental_model_last_memory_seen_at | 加列 |
| 7 | `c8b4e2a71f95` | maintenance_routines_skip_locked_schemas | 更新运维 routine（锁超时防御） |
| 8 | `f2a7c9d4b168` | add_mental_models_cron_index | 加 cron 索引 |

整链无分叉、无需要人工合并的多 head；迁移脚本对 PG 采用 schema-qualified raw SQL 与幂等守卫（"revision unstamped with the column already added —— retry must not …"），可直接 `alembic upgrade heads` / `hindsight-admin run-db-migration` 完成。

## 3. API 启动迁移机制

- `hindsight_api/engine/db/postgresql.py` 持有 `run_migrations()`；`memory_engine.py` 初始化时明确日志 `"Running database migrations…"` 并对所有 tenant schema fan-out。
- 因此**新镜像首次启动连上外部 PG 时会自动把库推到新 head**；升级程序的同时也就升级了数据库结构。
- 更稳妥做法：先以新镜像一次性执行 `hindsight-admin run-db-migration`（可加 `--skip-extension-reconcile` 加速），维护窗口内完成 DDL 后再切换服务。

## 4. 程序升级两条路线

**路线 A — 拉官方 ghcr 镜像（最直接）**
- 官方发布镜像：`ghcr.io/vectorize-io/hindsight:latest`（standalone 双服务）等，见 `hindsight-docs/docs/developer/installation.md`。
- 改 `docker/compose/hindsight/docker-compose.yaml` 的 `hindsight` 服务 `image:` 为官方 tag；现有全部环境变量在新版 config 均仍受支持（`HINDSIGHT_API_LLM_PROVIDER/BASE_URL`、`HINDSIGHT_API_EMBEDDINGS_*`、`HINDSIGHT_API_DATABASE_URL`、`HINDSIGHT_API_WORKER_ID`、`HINDSIGHT_CP_DATAPLANE_API_URL`）。
- 代价：失去本地自编译镜像的定制痕迹，镜像内容以上游最新发布为准（与我们合并的 upstream main 代码基本同源）。

**路线 B — 从本地 repo 自编译（延续 v0.8.6-wkj 先例）**
- 以 `docker/standalone/Dockerfile` 构建：`docker build -t hindsight-local:v0.9.x-wkj --build-arg INCLUDE_LOCAL_MODELS=false .`（外用 Ollama bge-m3 + MiniMax，不打包本地 ML；`PRELOAD_ML_MODELS` 亦可 false 提速）。
- 产出 API+CP 双服务镜像，expose 8888/9999，替换 compose `image:`。
- 耗时主要在 uv sync + npm ci + next build；首次可按需先只跑传统路径验证。

## 5. 风险与前置检查清单

1. **备份优先**：升级前对 `hindsight-db` 做 `pg_dump`（bind mount 数据卷在 `docker/vols/hindsight/pg_data`）。
2. **行为性差异**：v0.8.6→v0.9.x 跨度大，retain/consolidation/embedding/mental-model 语义均有演进；上线后用代表性 retain/recall/reflect 用例复验，尤其 MiniMax M2.7 走 openai compat 的 function-calling 表现。
3. **扩展一致性**：PG18 pgvector 容器与新版默认 vector/text-search 后端应匹配；迁移后 API 自检扩展索引即可。
4. **控制面板**：新版 CP 代建 UI 随镜像一起更新；升级后访问 9999 抽查 bank 列表/图表。
5. **worker ID**：compose 已设 `HINDSIGHT_API_WORKER_ID=hindsight-app`，容器重建后遗留 processing 任务可正确恢复，无需改。
6. **tenant 迁移**：若库中存在多租户 schema，API 启动迁移会对它们 fan-out；建议先跑 `run-db-migration` 看全 schema 列表结果。

## 6. 落地步骤（推荐）

```bash
# 1) 备份
docker exec hindsight-db bash -c "pg_dump -U hindsight_user -d hindsight_db" > /Users/weikejia/CODE/my-agent-group/docker/vols/hindsight/backup.sql

# 2) （可选）先用新镜像单独跑迁移验证
docker run --rm -e HINDSIGHT_API_DATABASE_URL=... <new-image> hindsight-admin run-db-migration

# 3) 改 compose image（路线 A 或 B）后
docker compose up -d --force-recreate hindsight
./start.sh   # 健康检查 API 8888 + CP 9999

# 4) 验证
curl -sf http://localhost:8888/health
```

## 7. 配套文档更新

- 升级后同步更新 `docker/compose/hindsight/KEYS.md`（版本与 99 迁移计数）与 `.env.example`（如需新增 embed/query prefix 等变量）。
