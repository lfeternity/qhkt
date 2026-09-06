# 启航课堂（qhkt）

启航课堂是一个面向在线教育场景的前后端分离项目，覆盖课程浏览与学习、课程搜索、订单与支付、优惠券、考试、问答、笔记、用户中心和管理后台等功能，并提供可选的 AI 学习助教服务。

## 项目组成

```text
qhkt/
├── qhkt                 Java 11 + Spring Boot 微服务集合
├── qhkt-protal          用户端（Vue 3 + Vite）
├── qhkt-admin            管理后台（Vue 3 + Vite）
├── qhkt-agent-python     AI 学习助教（FastAPI）
├── sql                  数据库初始化脚本
├── nginx.conf            Nginx 示例配置
└── README.md
```

Java 服务按领域拆分为认证、网关、用户、课程、媒资、搜索、学习、交易、支付、考试、营销、消息、数据和评论等模块。Java 包名统一使用 `com.qhkt`，Maven 模块和容器服务统一使用 `qhkt-*` 命名。

## 技术栈

- 后端：Java 11、Spring Boot 2.7、Spring Cloud、Spring Cloud Alibaba、MyBatis-Plus、MySQL、Redis、Nacos、RabbitMQ、Seata、Elasticsearch
- 用户端与管理后台：Vue 3、Vite、Vue Router、Pinia、Element Plus
- AI 助教：Python、FastAPI、SQLAlchemy、Alembic、LangChain/LangGraph、Qdrant、OpenTelemetry
- 部署：Maven、npm、Docker、Docker Compose、Nginx

## 环境要求

- JDK 11
- Maven 3.8+
- Node.js 16+ 和 npm
- Python 3.11+（运行 AI Agent 时使用）
- MySQL、Redis、Nacos 等基础设施（连接真实后端时需要）

## 快速开始

### Java 后端

```powershell
cd qhkt
mvn clean package -DskipTests
```

构建产物位于各模块的 `target` 目录。启动前请根据环境调整模块 `src/main/resources` 中的配置，并确保 Nacos、MySQL、Redis 等服务可访问。

### 用户端

```powershell
cd qhkt-protal
npm install
npm run dev
```

常用命令：

```powershell
npm run build       # development 构建
npm run build:test  # test 构建
npm run preview     # 预览构建结果
```

接口地址在 `src/config/proxy.js` 和 `vite.config.js` 中按运行环境配置。

### 管理后台

```powershell
cd qhkt-admin
npm install
npm run dev
```

构建命令：

```powershell
npm run build
npm run build:test
npm run build:prod
```

### Python AI 助教

```powershell
cd qhkt-agent-python
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev,ai]"
Copy-Item .env.example .env
uvicorn app.main:app --reload --port 8094
```

默认配置启用 mock 业务模式并关闭真实模型，可直接访问健康检查：

```text
GET http://localhost:8094/api/v1/health
```

生产环境请使用 `.env.production.example` 配置真实数据库、Redis、Qdrant、RabbitMQ、JWT 和模型服务，不要提交密钥。

## Docker 部署

Java 服务和两个前端目录都提供 Dockerfile。Python Agent 提供两套编排文件：

```powershell
cd qhkt-agent-python
docker compose -f docker-compose.prod.yml build
docker compose -f docker-compose.prod.yml up -d

# 集成环境（包含隔离的 MySQL、Redis、Qdrant 和 RabbitMQ）
docker compose -f docker-compose.integration.yml up --build
```

`nginx.conf` 提供用户端、管理后台、网关及基础设施服务的域名反向代理示例，部署时请替换为实际域名和后端地址。

## 数据库

`sql/` 目录包含认证、课程、考试、学习、媒资、消息、支付、营销、搜索、交易、用户和评论等初始化脚本，以及 Nacos、Seata、XXL-JOB 等基础设施脚本。请先创建目标数据库，再按依赖顺序执行对应脚本。

## 测试与检查

```powershell
cd qhkt
mvn test

cd ..\qhkt-agent-python
pytest -q
ruff check app tests
```

前端可使用 `npm run build` 验证生产构建。

## 目录约定

- 不提交 `.env`、真实凭据、运行日志、`node_modules`、Python 虚拟环境和构建产物。
- 对外展示名称使用“启航课堂”，代码、包名、模块和服务标识使用 `qhkt`。
- logo 资源使用 `启航课堂 / QIHANG ONLINE CLASSROOM` 版本；其他通用图标和 favicon 保持原有图形。
