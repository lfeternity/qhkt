# 数据库迁移

开发环境由 `DB_AUTO_CREATE=true` 自动创建表。生产环境应使用 Alembic 迁移，并在部署前关闭自动建表；当前 SQLAlchemy 模型对应 `ai_*` Agent 自有表，不能与业务库表混用。
