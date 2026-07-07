#!/bin/bash
set -e

cd "$(dirname "$0")"

# 检查 .env
if [ ! -f .env ]; then
    echo "❌ .env 不存在！请先创建："
    echo "   cp .env.example .env && vi .env"
    exit 1
fi

# 检查 Ollama 是否运行（宿主机）
if ! curl -sf http://localhost:11434/api/tags > /dev/null 2>&1; then
    echo "⚠️  宿主机 Ollama 似乎未运行。请确保 Ollama 已启动。"
    echo "   ollama serve"
    echo ""
fi

# 检查 bge-m3 模型是否已拉取
if ! curl -sf http://localhost:11434/api/tags | python3 -c "import sys,json; d=json.load(sys.stdin); models=[m['name'] for m in d.get('models',[])]; assert any('bge-m3' in m for m in models), 'bge-m3 not found'; print('✅ Ollama bge-m3 已就绪')" 2>/dev/null; then
    echo "⚠️  bge-m3 模型未找到，自动拉取..."
    ollama pull bge-m3
fi

echo "🚀 启动 Hindsight..."
docker compose up -d

echo ""
echo "等待服务就绪..."
sleep 5

# 等待 API 健康检查
for i in $(seq 1 30); do
    if curl -sf http://localhost:8888/health > /dev/null 2>&1; then
        echo "✅ API 已就绪！"
        break
    fi
    echo "  等待 API... ($i/30)"
    sleep 2
done

echo ""
echo "══════════════════════════════════════"
echo "  Hindsight 已启动"
echo ""
echo "  API:           http://localhost:8888"
echo "  API 文档:      http://localhost:8888/docs"
echo "  控制面板:      http://localhost:9999"
echo "  LLM:            MiniMax M2.7 (api.minimaxi.com)"
  echo "  Embeddings:     Ollama bge-m3 (宿主机)"
echo "  数据库:         PostgreSQL 18 + pgvector"
echo ""
echo "  查看日志: docker compose logs -f"
echo "  停止:     docker compose down"
echo "══════════════════════════════════════"
