# 系统架构

## 1. 项目定位

Chat Vault 是一个以结构化数据库为核心的 AI 对话归档系统。系统从不同 AI 客户端导入对话备份，将数据转换为统一的内部模型，保存并整理后，通过 CLI、Web API、Web 界面或 Markdown 等方式提供访问。


## 2. 分层结构

```text
外部备份数据
    │
    ▼
输入适配层（adapters/importers）
    │  转换为统一内部模型，并返回 ParseResult
    ▼
核心领域层（core）
    ├── 数据模型
    ├── 导入服务与清洗
    ├── 对话查询
    ├── 权限与发布状态
    └── 业务规则
    │
    ├── 数据存储层（storage）
    │
    ▼
输出适配层（adapters/exporters）
    ├── CLI
    ├── Web API
    ├── Markdown
    └── 未来的其他输出方式
```

### 核心领域层 `src/chat_vault/core/`

包含系统真正的业务规则。它不应依赖 Vue、FastAPI、HTTP 请求对象或 Chatbox 原始字段。

### 数据存储层 `src/chat_vault/storage/`

集中处理数据库连接、SQL、事务、建表和数据访问。业务层不应直接编写 SQL，而应通过 repository 访问数据库。

### 输入适配层 `src/chat_vault/adapters/importers/`

每一种外部格式对应一个适配器，例如当前的 `chatbox_v2.py`。适配器负责读取和解析原始文件，并转换成统一模型；通过 `ParseResult` 返回会话、错误和警告；不负责直接写数据库或生成网页。当前 Chatbox v2 适配器已完成 manifest、session、thread、branch、message 和 image attachment 的解析，但尚未提取文件附件。

### 输出适配层 `src/chat_vault/adapters/exporters/`

提供不同的访问和导出方式：

- `cli/`：本地命令行查看和导入；
- `web/`：FastAPI 应用、依赖、响应模型和路由；
- `markdown/`：导出 Markdown。

输出适配器应调用核心服务，而不是复制业务逻辑。

## 3. 统一数据模型

输入适配器必须把外部数据转换成统一的内部模型。当前模型位于 `core/models.py`，主要概念包括：

- `Conversation`：对话来源、标题、时间和 Branch 列表；
- `Branch`：主链或消息级分支，以及其 Message 和 Attachment；
- `Message`：角色、正文、思考内容、顺序、时间和所属 Branch；
- `Attachment`：Branch 中与消息关联的资源。

消息和附件不直接挂在 Conversation 上。Chatbox 专有字段只允许出现在 Chatbox 适配器内部。未来新增其他客户端适配器时，核心服务、数据库和前端应尽量无需大规模修改。

## 4. Chatbox 导入流程

```text
ZIP 备份
  → 识别格式
  → 找到会话目录和 session.json
  → 解析 JSON
  → 提取文本、思考内容、分支和图片附件
  → 转换为统一模型
  → 记录 ParseResult 警告或错误
  → 校验
  → 开启数据库事务
  → 保存对话、消息、分支、附件和原始数据
  → 提交事务
```

适配器需要兼容缺失字段、未知字段、`contentParts` 中未知类型、`messageForksHash` 和 `threads`。消息级旧版 `reasoningContent` 不在当前适配范围内；思考链仅处理 `contentParts` 中的 `reasoning` 片段。当前仅将 `image` 片段解析为附件，文件附件提取尚未实现。未知内容类型不应导致整个导入失败，应记录警告并按输入适配器设计决定是否保留。

## 5. 幂等导入

来源会话使用 `source_type + source_id` 作为稳定的唯一标识，例如：

```text
chatbox:9bedb698-c3de-48ac-...
```

重复导入同一备份时不得产生重复的 conversation 或 message。已有记录可以更新，原始数据应保留最新版本，所有修改必须在事务中完成；导入失败不能留下半成品数据。

## 6. 输出方式

### CLI

CLI 用于证明系统不依赖网站即可工作，计划支持：

```bash
python -m chat_vault.cli import backup.zip
python -m chat_vault.cli list
python -m chat_vault.cli show <conversation_id>
```

### Web API

API 只负责接收请求、校验参数、调用核心服务和返回响应。API 路由不应解析 Chatbox 文件、直接执行复杂 SQL 或堆积业务规则。

### Web 前端

前端只通过 API 获取统一格式的数据并提交用户操作，不解析 Chatbox 原始 JSON，也不实现核心权限规则。计划页面包括对话列表、对话详情、管理员管理界面和评论区域。

## 7. 权限边界

管理员可以查看所有导入数据、发布或隐藏对话、添加高亮或删除标记、管理评论和元数据。普通用户可以浏览公开对话并以匿名昵称发表评论。权限判断必须在后端核心服务或权限服务中完成，不能只依赖前端隐藏按钮。

## 8. 设计约束

- 原始 `session.json` 必须保留，以便重新解析和排查问题；
- 不在前端解析原始备份；
- 不在 API 路由中直接编写复杂 SQL；
- Markdown 和评论内容必须防范 XSS；
- 文件导入必须限制路径访问，不能读取任意本地文件；
- 单个异常会话应记录错误，不应无提示地导致整个批次崩溃；
- 优先级为：导入正确 > 数据可恢复 > 核心查询稳定 > 界面美观。

## 9. 当前实现状态

当前已完成 Chatbox v2 输入适配器、核心模型的第一版重构以及基础导入、存储、查询、权限和输出模块的文件骨架。`models.py` 已完成内容域关系重构，但存储层与导入服务仍需按新模型完成衔接；文件附件提取和跨文件日志处理尚未完成。测试文件不作为本节实现状态的判断依据。