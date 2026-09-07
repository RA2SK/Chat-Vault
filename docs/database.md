# 数据库设计

## 1. 数据库定位

SQLite 是 Chat Vault 的核心数据存储，而不是 Web 层的附属品。初期使用 Python 标准库 `sqlite3` 即可，待核心结构稳定后再考虑 ORM 或其他数据库。

数据库相关代码集中在 `src/chat_vault/storage/`：

- `database.py`：连接、初始化和事务管理；
- `repositories.py`：面向业务的数据访问接口；
- `schema.sql`：建表和索引定义；
- `migrations/`：未来的结构迁移文件。

业务服务不应直接执行 SQL，API 路由也不应绕过 repository 操作数据库。

## 2. 初步实体

系统计划包含以下实体：

| 实体 | 作用 |
| --- | --- |
| `sources` | 外部数据来源，例如 Chatbox |
| `conversations` | 对话基本信息和发布状态 |
| `messages` | 对话中的消息、正文和思考内容 |
| `branches` | 对话分支和分叉关系 |
| `users` | 管理员或其他用户身份 |
| `comments` | 用户对消息或对话的评论 |
| `admin_marks` | 管理员添加的高亮、删除等标记 |
| `imports` | 每次导入任务的状态、结果和错误信息 |

核心关系如下：

```text
一个 source       → 多个 conversation
一个 conversation → 多条 message
一个 conversation → 多个 branch
一个 branch       → 多条 message
一条 message      → 多条 comment
一条 message      → 多个 admin_mark
一个 user         → 多条 comment
```

## 3. 统一标识和幂等性

外部来源的会话不能只依赖数据库自增 ID。每个来源会话必须保存稳定的来源类型和来源 ID，并对二者建立唯一约束：

```text
(source_type, source_id) = 唯一来源会话
```

例如：

```text
source_type = chatbox
source_id   = 9bedb698-c3de-48ac-...
```

消息也应保存来源消息 ID或其他稳定标识，以便重复导入时更新已有记录而不是插入重复数据。

## 4. 原始数据保存

每个 Chatbox `session.json` 都必须保留。原始数据的用途包括：

1. Chatbox 格式变化后重新解析；
2. 基于历史数据开发新的适配器；
3. 排查导入错误；
4. 避免清洗过程造成不可逆的信息丢失。

初期可以把原始 JSON 保存到数据库的 `raw_data` 字段中；数据量较大时，可以保存到 `data/raw/`，并在数据库中记录文件路径和哈希值。无论采用哪种方式，都应保留原始数据和其来源关联。

## 5. 导入事务

导入一个备份时，建议按以下顺序处理：

1. 识别并解析文件；
2. 转换成统一模型并校验；
3. 开启数据库事务；
4. 创建或更新 conversation；
5. 保存原始 JSON；
6. 创建或更新 messages；
7. 创建或更新 branches；
8. 写入 imports 记录和统计结果；
9. 全部成功后提交事务。

如果任何关键步骤失败，应回滚本次事务，避免出现只有对话没有消息、只有消息没有原始数据等半成品状态。

## 6. 建议字段方向

以下是设计方向，实际字段应根据实现和迁移需求进一步确定：

### `conversations`

- 内部数据库 ID；
- `source_id` 和 `source_type`；
- 标题；
- 创建和更新时间；
- 公开/隐藏状态；
- 原始元数据；
- 创建时间和更新时间。

### `messages`

- 内部数据库 ID；
- 所属 conversation 和 branch；
- 来源消息 ID；
- 角色；
- 正文；
- 思考内容；
- 展示顺序；
- 消息时间；
- 模型信息和其他元数据。

### `branches`

- 所属 conversation；
- 来源分支 ID；
- 分叉消息来源 ID；
- 分支顺序；
- 是否为当前分支。

### `imports`

- 导入来源和文件信息；
- 开始与结束时间；
- 成功、失败和跳过数量；
- 错误摘要；
- 原始文件哈希。

## 7. 权限和发布状态

原始数据默认不公开。管理员可以发布或隐藏对话、设置高亮和删除标记；普通用户只能查看公开数据并发表评论。

权限不能只通过前端按钮控制，必须由后端服务校验。管理员密码不得明文保存，评论内容也不能未经处理直接作为 HTML 插入页面。

## 8. 数据库演进

修改数据库时应遵循：

1. 先说明实体、关系和约束；
2. 修改 `schema.sql` 或新增 migration；
3. 同步修改 repository；
4. 再修改 service 和 API；
5. 尽量保证旧数据能够迁移；
6. 为幂等导入和关键约束补充测试。