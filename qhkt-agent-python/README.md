# qhkt Python Agent

独立的启航课堂学习助教服务，与现有 Java 11/Spring Boot 2.7 微服务通过 HTTP 集成。

## 本地启动

```powershell
cd qhkt-agent-python
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev,ai]"
Copy-Item .env.example .env
uvicorn app.main:app --reload --port 8094
```

默认 `MOCK_BUSINESS_MODE=true`、`AI_ENABLED=false`，不依赖 MySQL、Redis、Qdrant 或真实模型即可验证接口。健康检查：

```text
GET http://localhost:8094/api/v1/health
```

## 网关接入

网关外部路径为 `/ais/api/v1/**`，服务内部路径为 `/api/v1/**`。第一阶段建议使用静态内部地址：

```text
AGENT_SERVICE_URI=http://qhkt-agent-python:8094
```

Python 服务接收 Gateway 注入的 `user-info`、`role-info` 和 `requestId`。生产环境将 `JWT_ENABLED=true` 后，额外校验 RS256 JWT/JWKS。

## 已实现能力

- 会话、消息、反馈、用户画像和 SSE 流式对话；模型不可用时自动使用规则降级。
- 7 个只读课程工具，以及学习计划、笔记、提问的 Prepare/Confirm/Cancel 流程（幂等、过期、取消和二次鉴权）。
- 课程知识文档发布、SRT/VTT/TXT 字幕上传、可选 ASR 转写、混合检索、可选 Rerank、引用时间轴和 Qdrant 适配。
- RabbitMQ 课程上下架事件、异步摄取重试/死信状态、Prompt 版本激活、Prometheus 指标和 OpenTelemetry 请求 Span。

运行测试和代码检查：

```powershell
pytest
ruff check app tests
```

生产环境建议将 `DB_AUTO_CREATE=false`，先执行 `alembic upgrade head`，再启动 Uvicorn。

生产运维脚本：

```bash
python scripts/preflight.py
python scripts/backup.py --output /var/backups/qhkt-agent/<timestamp>
python scripts/restore_smoke.py /var/backups/qhkt-agent/<timestamp>
```

`preflight.py` 会检查生产必需配置及 Qdrant/媒资连通性；备份脚本保存关系库和向量快照元数据，恢复 smoke 只校验归档完整性，不会修改线上数据。

## VM 部署

生产编排文件为 `docker-compose.prod.yml`，只依赖现有 `heima-net` 网络和基础设施容器。首次部署时复制
`.env.production.example` 为 `.env.production`，填入密钥后执行：

```bash
docker-compose -f docker-compose.prod.yml build
docker-compose -f docker-compose.prod.yml up -d
docker-compose -f docker-compose.prod.yml ps
```

集成验收可使用 `docker-compose.integration.yml`，它会启动隔离的 MySQL、Redis、Qdrant 和 RabbitMQ，并等待健康检查通过后再启动 Agent：

```bash
docker-compose -f docker-compose.integration.yml up --build
```

Gateway 的 `AGENT_SERVICE_URI` 必须设置为 `http://qhkt-agent-python:8094`。Java Agent 已移除，部署后确认该容器为唯一 Agent 实例并保持健康状态。

## 生产配置

复制 `.env.example` 到密钥管理系统或容器环境，不要把真实 API Key、数据库密码和 JWT 配置提交到 Git。生产建议使用 MySQL、Redis、Qdrant 和 RabbitMQ，并关闭 `MOCK_BUSINESS_MODE`。
