# 开发计划

## 一、更新日志

### 2026-09-10

- 重构 `chatbox_v2.py`，完成 Chatbox v2 备份的主要解析链路。
- 重构 `models.py`，调整 Conversation、Branch、Message 和 Attachment 的关系。
- 同步修订 `architecture.md`、`importers.md` 和 `models.md`，使文档与当前结构一致。

## 三、已发现但尚未完成的内容

### 按文件列出

- `src/chat_vault/adapters/importers/chatbox_v2.py`
  - 添加对文件附件的识别、资源索引和提取。

- `src/chat_vault/core/models.py`
  - 根据存储层实际实现继续补充模型关系的入库衔接。

- `src/chat_vault/core/import_service.py`
  - 实现适配器调用、导入结果处理、事务和原始备份归档。

- `src/chat_vault/storage/schema.sql`
  - 按当前模型关系完成数据库表结构和约束。

- `src/chat_vault/storage/database.py`
  - 完成数据库连接、初始化和事务支持。

- `src/chat_vault/storage/repositories.py`
  - 完成 Conversation、Branch、Message、Attachment 等对象的持久化和关系回填。

- `src/chat_vault/core/query_service.py`
  - 实现对话、分支和消息查询。

- `src/chat_vault/core/permission_service.py`
  - 实现发布状态、管理员操作和访问权限判断。

- `src/chat_vault/adapters/exporters/`
  - 实现 CLI、Markdown、Web API 和其他输出逻辑。

### 不属于单个文件的更新内容

- 添加跨文件的统一日志处理模块，使适配器、导入服务、存储层和输出层使用一致的日志接口。
