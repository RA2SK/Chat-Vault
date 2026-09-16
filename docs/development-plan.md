# 项目开发台账

## 一、更新日志

### 2026-09-15（接口契约层）

- 完成 `modules/interfaces/` 下全部接口契约文件的编写：`repositories_intf.py`、`importing_intf.py`、`querying_intf.py`、`publishing_intf.py`、`moderation_intf.py`、`comments_intf.py`、`users_intf.py`，并新增 `exporting_intf.py` 承载内容重新打包契约，`__init__.py` 统一导出全部契约。
- 契约一律使用 `typing.Protocol` 按结构匹配，具体实现不继承契约，也不被契约导入；契约层只依赖 `core` 与接口层内部的其他契约文件。
- 仓储契约统一命名为 `*Store`，服务契约统一命名为 `<能力>ServiceContract`，避免与同名的具体实现类冲突；输入形状统一命名为 `*Request`、`*Query`、`*Submission`，输出形状统一命名为 `*Detail`、`*View`。
- 把两个描述"一次调用产出形状"的数据搬运到接口层：`ParseResult` 从 `adapters/base.py` 移到 `importing_intf.py`，`ConversationDetail` 从 `services/querying.py` 移到 `querying_intf.py`。原位置保留同名再导出，因此现有调用点无需改动。
- `QueryService` 新增 `get_message()` 与 `get_message_conversation_source_id()`，用于消除 `services/comments.py` 直接访问 `query_service.message_repository` 的跨层调用。
- `bootstrap.py` 的 `ServiceContainer` 字段改为按契约类型标注，装配仍使用具体实现。
- `pyproject.toml`：`requires-python` 提升为 `>=3.12`，ruff `target-version` 同步改为 `py312`；dev 依赖新增 `pyright`，并新增 `[tool.pyright]` 配置段，`include` 指向 `src`。
- 新增 `tests/test_interface_contracts.py`，用 `isinstance()` 对具体实现做契约方法名的运行时冒烟检查。`isinstance()` 只比较方法名，不比较签名，签名一致性由 pyright 负责。

### 2026-09-15（仓储层重构）

- 一步到位完成仓储层重构：`repositories.py` 拆分为 `conversations.py`、`messages.py`、`moderation.py`、`comments.py`、`users.py` 和 `imports.py`，并新增 `mappings.py` 集中持有列名知识、负责数据库行与核心模型的转换。
- 仓储层内部统一用自增 rowid 维持父子外键，rowid 不进入模型；对外一律以 `source_id` 标识，需要写父子关系时由调用方显式传入父节点的 `source_id`，并做显式预校验。
- `mappings.py` 的时间转换拆分为 `from_db_datetime()` 与 `from_db_datetime_optional()`，分别对应 NOT NULL 列和可空列，各调用点按 `schema.sql` 重新归位。
- 完成 `models.py` 拆分：内容、互动、身份和运维四个业务域的模型分别落入 `core/models/` 下的 `content.py`、`interaction.py`、`identity.py` 和 `operations.py`；枚举抽到 `core/enums.py`，标识符与通用类型抽到 `core/types.py`。内容模型改用 `source_id` 作为身份，不再暴露数据库主键。
- 重构 `chatbox_v2.py`：`source_type` 改用 `SourceType` 枚举，`preprocess.with_source_namespace()` 与 `adapters/base.py` 同步改为接收枚举；`_parse_message()` 返回值改为 `Message | None`，并显式校验 `MessageRole`，无法识别的角色降级为警告后跳过；删除 `_parse_attachment()`。
- **附件与分支脱钩**：`Message` 新增 `attachments` 字段，`Branch` 删除该字段；`importing.py` 的保存流程与附件校验、`querying.py` 的 `get_conversation_detail()` 同步改为按消息聚合附件。
- 补齐 `Conversation.source_archive` 缺口，导入时写入原始备份文件名。
- 适配 `importing.py` 与 `querying.py` 到新的仓储接口与模型定义，导入流程端到端验证通过。

### 2026-09-14

- 新增 `apps/server/src/core/enums.py`、`core/types.py` 与 `apps/server/src/api/` 下的 `schemas.py`、`dependencies.py`、`exception_handlers.py`。
- `core/services.py` 重命名为 `bootstrap.py`；`modules/services/` 下的服务文件按业务重命名为 `importing.py`、`querying.py`、`publishing.py`、`moderation.py`、`comments.py` 和 `users.py`。
- `modules/interfaces/` 按业务能力重新拆分为 `importing_intf.py`、`querying_intf.py`、`publishing_intf.py`、`moderation_intf.py`、`comments_intf.py`、`users_intf.py` 和 `repositories_intf.py`。
- 删除 `modules/services/dto.py`，其内容按所属业务分别吸收到对应的服务文件或接口文件中。

### 2026-09-12

- 完成核心业务层的最小功能实现：导入、查询、权限服务以及服务容器已完成基础组装，但相关文件目前均属于“已部分完成”。
- `import_service.py` 已支持文件导入、解析结果处理、基础校验、幂等保存和导入批次统计；完整事务编排、复杂错误恢复和更多业务规则尚未实现。
- `query_service.py` 已支持对话列表、已发布对话列表、对话详情、分支、消息和附件的基础查询；复杂搜索、筛选、排序和分页尚未实现。
- `permission_service.py` 已完成最小权限判断；真正的认证系统、会话管理和持久化权限体系尚未实现。
- `services.py` 已完成数据库连接、Repository 和核心服务的基础组装；更完善的生命周期管理和事务边界尚未实现。
- `core/__init__.py` 已完成核心模型和服务的基础公共导出；更复杂的业务初始化和导出控制尚未实现。
- `repositories.py` 新增 `ConversationRepository.list_all()`，用于支持未发布对话的基础列表查询。

### 2026-09-11

- 完成 `schema.sql` 第一版数据库结构，暂不持久化 `MessageRevision`。
- 完成 `database.py` 的 SQLite 连接、外键启用、数据库初始化和事务管理。
- 完成 `repositories.py` 中 8 个基础 Repository 的基本增删改查能力。
- 为 `UserRepository` 增加用户更新能力。
- 为 `AttachmentRepository` 增加附件更新和删除能力。
- 当前数据库和仓储层属于基础版本，后续需要随着 `models.py` 的模型关系和字段完善继续同步调整。

### 2026-09-10

- 重构 `chatbox_v2.py`，完成 Chatbox v2 备份的主要解析链路。
- 重构 `models.py`，调整 Conversation、Branch、Message 和 Attachment 的关系。
- 同步修订 `architecture.md`、`importers.md` 和 `models.md`，使文档与当前结构一致。

## 二、程序文件完成情况

### 已完成

- `apps/server/src/core/enums.py`：完成角色、来源、附件类型、评论目标、标记类型和导入状态等跨模块共享的枚举取值。
- `apps/server/src/core/types.py`：完成业务标识符 NewType、`source_ref` 约定、校验值结构和应用侧 `new_id()`。
- `apps/server/src/core/models/__init__.py`：完成核心模型的统一导出，调用方继续使用 `core.models` 这一稳定路径。
- `apps/server/src/core/models/content.py`：完成对话、分支、消息和附件的内容图定义，以 `source_id` 作为身份，附件归属消息。
- `apps/server/src/core/models/interaction.py`：完成评论、管理员标记和消息编辑历史模型。
- `apps/server/src/core/models/identity.py`：完成用户模型。
- `apps/server/src/core/models/operations.py`：完成导入批次模型。
- `apps/server/src/modules/adapters/base.py`：完成输入适配器接口和 `source_type` 类属性约定；`ParseResult` 的定义已移到 `modules/interfaces/importing_intf.py`，本文件保留同名再导出。
- `apps/server/src/modules/adapters/detector.py`：完成输入格式检测入口。
- `apps/server/src/modules/adapters/__init__.py`：完成适配器注册。
- `apps/server/src/modules/adapters/preprocess.py`：完成 `source_id` 命名空间拼接和通用预处理校验。
- `apps/server/src/modules/adapters/chatbox_v2.py`：完成 Chatbox v2 ZIP 的格式识别、manifest、resource 索引、session、thread、conversation、branch、message、image attachment 和 warning 处理。
- `apps/server/src/modules/repositories/database.py`：完成 SQLite 连接、外键设置、数据库初始化和事务管理。
- `apps/server/src/modules/repositories/schema.sql`：完成数据库表、字段、索引和外键约束，暂不持久化 `MessageRevision`。
- `apps/server/src/modules/repositories/mappings.py`：完成数据库行与核心模型之间的转换，集中持有列名知识以及时间、校验值的双向转换。
- `apps/server/src/modules/repositories/conversations.py`：完成 `ConversationRepository` 和 `BranchRepository`。
- `apps/server/src/modules/repositories/messages.py`：完成 `MessageRepository` 和 `AttachmentRepository`。
- `apps/server/src/modules/repositories/imports.py`：完成 `ImportBatchRepository`。
- `apps/server/src/modules/repositories/users.py`：完成 `UserRepository`。
- `apps/server/src/modules/repositories/comments.py`：完成 `CommentRepository`。
- `apps/server/src/modules/repositories/moderation.py`：完成 `AdminMarkRepository`。
- `apps/server/src/modules/repositories/__init__.py`：完成 8 个仓储类的统一导出。
- `apps/server/src/bootstrap.py`：完成数据库连接、8 个仓储和两个业务服务的依赖组装。

### 已部分完成

- `apps/server/src/modules/services/importing.py`：已完成适配器调用、解析结果处理、基础校验、幂等保存、`source_archive` 归档信息和导入批次统计；完整事务编排、复杂错误恢复和更多边界规则尚未实现。
- `apps/server/src/modules/services/querying.py`：已完成对话列表、已发布对话列表、对话详情以及分支、消息和附件的基础查询；复杂搜索、筛选、排序和分页尚未实现。
- `apps/server/src/modules/services/users.py`：只有预先准备好的最小权限判断；用户注册、信息维护和密码保存尚未实现。
- `apps/server/src/modules/services/publishing.py`：只有预先准备好的最小发布权限判断；发布内容整理和展示字段处理尚未实现。
- `apps/server/src/modules/services/moderation.py`：只有预先准备好的最小管理权限判断；管理员编辑、标记和维护流程尚未实现。
- `apps/server/src/modules/services/comments.py`：只有预先准备好的最小评论权限判断；评论的创建、读取、修改和删除尚未实现。
- `apps/server/src/core/__init__.py`：仅完成基础公共导出；更复杂的业务初始化和导出控制尚未实现。
- `apps/server/src/modules/interfaces/`：契约层已完整建立。`repositories_intf.py`、`importing_intf.py`、`querying_intf.py`、`publishing_intf.py`、`moderation_intf.py`、`comments_intf.py`、`users_intf.py`、`exporting_intf.py` 与 `__init__.py` 均已写入契约；仍属"已部分完成"，因为部分契约按当前实现现状声明（`PublicationServiceContract.get_conversation_for_view` 仍返回 `ConversationDetail`，`UserServiceContract.register`/`get` 仍返回带 `password_hash` 的 `User`），尚未收窄为契约中声明的 `PublishedConversationView` 与 `UserView`；`exporting_intf.py` 只声明了形状，没有任何实现。

### 未开工

- `apps/server/src/api/routes.py`、`schemas.py`、`dependencies.py`、`exception_handlers.py`：文件已建立，Web API 路由、请求响应校验、依赖提供和异常转换尚未开始。
- `apps/server/src/modules/interfaces/exporting_intf.py`：内容重新打包契约已声明形状，输出端实现、Web 数据提交和落盘编排尚未开始。
- `apps/server/src/utils/hashing.py`、`apps/server/src/utils/logging.py`：文件已建立，校验和计算与统一日志逻辑尚未开始。
- `apps/server/src/cli.py`、`apps/server/src/main.py`：文件已建立，CLI 入口和 Web 服务启动逻辑尚未开始。
- `apps/client/src/`：前端仅建立基础目录和项目入口，对话浏览、Markdown 模拟渲染、搜索、评论和管理界面尚未开始。

## 三、已发现但尚未完成的内容

- `apps/server/src/modules/adapters/chatbox_v2.py`
  - 添加对文件附件的识别和提取，目前只解析图片附件。

- `apps/server/src/core/models/content.py`
  - 内容域的关系和字段仍需随业务补充。
  - 未来需要把原始文件从 Conversation 当中拆出来，独立一个单独的模型管理原始文件，但不是业务重点，可以等到第二种适配器出现的时候更新。

- `apps/server/src/core/models/interaction.py`
  - `MessageRevision` 目前只有模型定义，尚未持久化。
  - `AdminMark` 和 `Comment` 与 Message 或 Conversation 的关联关系待定。

- `apps/server/src/modules/services/importing.py`
  - 完整事务编排、复杂错误恢复和更多导入边界规则尚未实现。

- `apps/server/src/modules/services/querying.py`
  - 复杂搜索、筛选、排序和分页尚未实现。

- `apps/server/src/modules/services/users.py`
  - 真正的认证系统、会话管理和持久化权限体系尚未实现。

- `apps/server/src/modules/services/publishing.py`、`moderation.py`、`comments.py`
  - 目前只有预先准备好的权限校验代码，业务主体尚未实现。

- `apps/server/src/bootstrap.py`
  - 更完善的服务生命周期管理和事务边界尚未实现。

- `apps/server/src/core/__init__.py`
  - 更复杂的业务初始化和导出控制尚未实现。

- `apps/server/src/modules/repositories/schema.sql`
  - 当前为基础版本；未来需要根据 `core/models/` 的字段、关系和约束变化继续完善。

- `apps/server/src/modules/repositories/database.py`
  - 基础连接和事务功能已完成；未来可能根据数据库迁移和模型演化需求扩展。

- `apps/server/src/modules/repositories/`
  - 基础 Repository 已完成；未来需要根据 `core/models/` 的完善同步增加或调整持久化字段、关系和查询接口；仓储层收到的修改需求也在累积，需要安排一次统一调整。

### 不属于单个文件的更新内容

- 完成 Web API 与前端之间的数据接口。
- 完成前端对话展示、Markdown 模拟渲染、评论回传和未来下载功能。
- 添加跨文件的统一日志处理模块，使适配器、导入服务、存储层和输出层使用一致的日志接口。
- 仓储层已对外统一以 `source_id` 标识内容对象，数据库主键不再离开持久化层；后续新增查询接口时需要继续保持这一约定。
