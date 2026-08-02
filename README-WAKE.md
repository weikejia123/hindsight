# Hindsight — Agent Memory That Learns

| 字段 | 值 |
|------|-----|
| 用途 | Agent 记忆系统，让 Agent 不仅记住还能学习，超越 RAG 和知识图谱 |
| 应用场景 | AI Agent 跨会话记忆、用户画像持久化、行为学习 |
| 标签 | agent-memory|AI记忆|LLM|learning |
| 技术栈 | Python|Docker|PostgreSQL|OpenAI/Anthropic/Ollama |
| 内部版本 | V2-20260803 |
| 依赖 | Docker（推荐）或 `pip install hindsight-all`（嵌入式） |
| 关联 | Hermes Agent（当前默认 memory provider，本地 Docker 部署中） |

## 来源

- 上游：https://github.com/vectorize-io/hindsight
- Fork：https://github.com/weikejia123/hindsight
- Gitea 备份：http://localhost:3000/dzsoft/hindsight.git
- 本地路径：`projects/memory/hindsight/`
- 分支：`main` 跟踪上游（纯净） / `wkj-dev` 二开（含 my-docker 部署配置）

## 部署方式

详见 `README.md` 或 `docker/` 目录。
