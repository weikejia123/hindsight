# Hindsight MiniMax M2.7 + Ollama bge-m3 部署

| 字段 | 值 |
|------|-----|
| LLM | MiniMax M2.7 |
| Embeddings | Ollama bge-m3（宿主机） |
| 数据库 | PostgreSQL 18 + pgvector（容器内） |
| 版本 | ghcr.io/vectorize-io/hindsight:latest |
| 端口 | API: 8888 / CP: 9999 |

---

## 所需密钥

以下变量写入 `my-docker/.env`（.gitignore 已排除）：

| 变量 | 值 | 来源 |
|------|-----|------|
| `MINIMAX_API_KEY` | `sk-cp-...` | MiniMax 控制台（api.minimaxi.com） |
| `HINDSIGHT_DB_PASSWORD` | 自定 | 任意强密码 |

实际密钥填入 `.env` 文件，示例见下方。

## 前置条件

1. **Ollama** 已在宿主机运行，`bge-m3` 模型已拉取
2. **Docker Desktop** 已安装（macOS）

## 启动

```bash
cd my-docker
# 首次：填写 .env
cp .env.example .env
vi .env    # 填入 MiniMax key 和 DB 密码

# 启动
./start.sh
# 或
docker compose up -d
```

## 访问

| 服务 | 地址 |
|------|------|
| API | http://localhost:8888 |
| 控制面板 | http://localhost:9999 |
| API 文档 | http://localhost:8888/docs |
