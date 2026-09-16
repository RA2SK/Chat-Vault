# 项目开发台账

## 一、更新日志

### 2026-09-16（事务边界、重复导入与分支更新）

- 事务边界从"依赖 SQLite 隐式事务"改为"在服务层显式声明"：`repositories/database.py` 的 `transaction()` 上下文管理器补齐调用点，`ImportService`、`CommentService`、`ModerationService`、`UserService`、`PublishingService` 的每个写操作各自包在一个 `with transaction(connection):` 里，使"一次业务操作 = 一个事务"在代码里可直接读出来。`ServiceContainer.close()` 在关闭连接前先回滚未提交的事务，避免关闭时静默丢数据。
- `ImportService` 新增 `connection` 构造参数，直接持有数据库连接用于声明事务边界，而不是绕回某个仓储去取连接。`ServiceContainer` 相应地传入同一个连接。
- 导入幂等性补上"整份文件是否已导入过"的判断：`ImportBatchRepository.get_by_file_hash()` 与 `ImportBatchStore.get_by_file_hash()` 新增，`ImportService.find_duplicate_import()` 按文件内容摘要判断，命中已成功的批次时 `import_results()` 直接返回该批次，不再重复写入。摘要计算抽成模块级 `_hash_file()`，创建批次和重复检测共用同一条路径。`idx_import_batches_file_hash` 索引在 `schema.sql` 中已存在，无需迁移。
- 修复"重新导入抹掉消息编辑"：`_save_message()` 在覆盖已有消息前会保留 `edited_at`/`edited_by`，并且对已经编辑过的消息直接跳过写入，因此重新导入不会把内容回退到原始版本，也不会留下"内容已还原但编辑记录仍在"的自相矛盾状态。该保护与已有的 `is_published` 保护采用同一种思路。
- 修复分支更新静默失效：`BranchRepository.update()` 与 `BranchStore.update()` 新增，`_save_branch()` 原来只是把 `is_current` 从已有记录复制到内存对象上、没有任何写库动作，属于无声的空操作；现在会在保留 `is_current`（由管理侧控制）的前提下把分支其余字段写回数据库。
- `AdminMarkRepository.list_by_message()` 的 `is_deleted = 0` 过滤从服务层的 Python 列表推导下推到 SQL，`ModerationService.list_marks()` 变为直接转发。
- 删除 `modules/adapters/detector.py`：该文件只提供 `detect_format()`，没有任何调用方，`adapters/__init__.py` 也不导入它，格式识别实际由 `BaseImporter.detect` 在 `ImportService.import_file()` 中完成。
- 数据库文件默认路径由 `data/chat_vault.db` 改为 `data/raw/chat_vault.db`。`data/raw/` 已在 `.gitignore` 中，因此不再有误提交数据库文件的风险；等程序完成、数据库回到 `data/` 下时再调整忽略规则。
- `AttachmentRepository.delete()` 当前没有调用方，契约文档补充说明它是为后续附件管理预留的接口，不是遗留代码。
- 契约文档同步：`ImportServiceContract` 的"不承诺事务边界"改为描述实际的事务语义，并补充重复导入的说明；`repositories_intf.py` 的契约不对称清单删掉了已经补齐的两条。
- `ServiceContainer.close()` 改为幂等：容器可能被调用方和退出流程各关一次，重复关闭会落到已关闭的连接上并抛出 `ProgrammingError`，因此用私有标记位挡住第二次关闭。
- 新增 `tests/test_persistence_and_import.py`，覆盖关闭连接后重新打开数据库仍能读到写入结果、重复导入保留消息编辑且未编辑的消息允许覆盖、分支更新写库同时保留 `is_current`、同一份文件内容被识别为重复导入且不产生新批次、软删除的管理员标记不出现在查询结果里、普通用户添加标记被拒绝。
- `.gitignore` 增加 `data/*.db`，为数据库将来从 `data/raw/` 迁回 `data/` 提前挡住误提交。

### 2026-09-16（管理员初始化与对话级评论聚合）

- `UserService` 新增 `register_admin()` 与 `has_admin()`，`register()` 与 `register_admin()` 共用私有的 `_create_user()` 做用户名与密码校验，两者唯一区别是角色。刻意不做"第一个用户自动升格"，创建管理员必须由调用方明确表达意图。
- `UserRepository` 与 `UserStore` 新增 `has_role(role)`，只回答"是否存在某类角色"，不提供"列出全部用户"，与既有的"不扩大用户信息暴露面"决定保持一致。
- `bootstrap.py` 新增模块级函数 `ensure_initial_admin(container, username, password)`：库中已有管理员时直接返回 `False`，因此重复调用安全；用户名或密码任一为空时跳过并返回 `False`，这是"不启用自动初始化"的开关。函数不提供任何默认口令，默认口令写进代码等于公开管理员入口。该函数刻意不放进 `ServiceContainer.create()`：`create()` 负责结构装配，测试还会用 `initialize=False` 跳过建表，把数据初始化混进去会让职责和测试语义都变模糊。
- 修正角色默认值不一致：`core/models/identity.py` 的 `User.role` 默认值由 `UserRole.ADMIN` 改为 `UserRole.USER`，`schema.sql` 的 `users.role` 默认值由 `'admin'` 改为 `'user'`。此前模型与数据库默认管理员、而服务层显式传普通用户，三处互相矛盾。
- `CommentRepository` 与 `CommentStore` 新增 `list_by_conversation_including_messages()`：消息级评论在库内不记录所属对话，该方法沿 `comments -> messages -> branches -> conversations` 逐级回溯归属，把对话评论与消息评论合并后按时间线排序。`list_by_conversation()` 语义不变，仍只返回直接挂在对话下的评论。
- 三个评论查询方法的 `is_deleted = 0` 过滤从服务层的 Python 列表推导下推到 SQL，服务层不再重复过滤，仓储契约的文档也补上了"只返回有效评论"的说明。
- 新增 `tests/test_admin_and_comments.py`，覆盖管理员注册、`has_admin`、`ensure_initial_admin` 的跳过与幂等行为，以及对话级评论聚合的合并、软删除过滤和跨对话隔离。

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
- `apps/server/src/bootstrap.py`：完成数据库连接、8 个仓储和两个业务服务的依赖组装。服务级事务边界已在各服务内声明，跨服务的事务编排和更完整的生命周期管理尚未实现。

### 已部分完成

- `apps/server/src/modules/services/importing.py`：已完成适配器调用、解析结果处理、基础校验、幂等保存（含按文件内容摘要的重复导入检测）、`source_archive` 归档信息和导入批次统计；每个导入操作的事务边界已落地，更复杂的错误恢复和更多边界规则尚未实现。
- `apps/server/src/modules/services/querying.py`：已完成对话列表、已发布对话列表、对话详情以及分支、消息和附件的基础查询；复杂搜索、筛选、排序和分页尚未实现。
- `apps/server/src/modules/services/users.py`：已完成权限判断、普通用户注册、管理员注册、`has_admin` 检查、认证与改密；返回值的 `UserView` 收窄、用户信息维护和会话管理尚未实现。`register()`/`get()` 目前仍返回带 `password_hash` 的 `User`，调用方不得直接把该对象交给前端。
- `apps/server/src/modules/services/publishing.py`：只有预先准备好的最小发布权限判断；发布内容整理和展示字段处理尚未实现。
- `apps/server/src/modules/services/moderation.py`：只有预先准备好的最小管理权限判断；管理员编辑、标记和维护流程尚未实现。
- `apps/server/src/modules/services/comments.py`：已完成评论的创建、按对话查询、按消息查询、对话级聚合查询和软删除；评论编辑按设计不提供，修改意见只能删除后重发。
- `apps/server/src/core/__init__.py`：仅完成基础公共导出；更复杂的业务初始化和导出控制尚未实现。
- `apps/server/src/modules/interfaces/`：契约层已完整建立。`repositories_intf.py`、`importing_intf.py`、`querying_intf.py`、`publishing_intf.py`、`moderation_intf.py`、`comments_intf.py`、`users_intf.py`、`exporting_intf.py` 与 `__init__.py` 均已写入契约；仍属"已部分完成"，因为部分契约按当前实现现状声明（`PublicationServiceContract.get_conversation_for_view` 仍返回 `ConversationDetail`，`UserServiceContract.register`/`get` 仍返回带 `password_hash` 的 `User`），尚未收窄为契约中声明的 `PublishedConversationView` 与 `UserView`；`exporting_intf.py` 只声明了形状，没有任何实现。

### 未开工

- `apps/server/src/api/routes.py`、`schemas.py`、`dependencies.py`、`exception_handlers.py`：文件已建立，Web API 路由、请求响应校验、依赖提供和异常转换尚未开始。
- `apps/server/src/modules/interfaces/exporting_intf.py`：内容重新打包契约已声明形状，输出端实现、Web 数据提交和落盘编排尚未开始。
- `apps/server/src/utils/hashing.py`、`apps/server/src/utils/logging.py`：文件已建立，校验和计算与统一日志逻辑尚未开始。
- `apps/server/src/cli.py`、`apps/server/src/main.py`：文件已建立，CLI 入口和 Web 服务启动逻辑尚未开始。`bootstrap.ensure_initial_admin()` 目前只被测试调用，等入口文件落地后应由启动流程读取环境变量并调用它。
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
  - 更复杂的错误恢复和更多导入边界规则尚未实现。
  - 同一个批次内的部分失败目前按整体回滚处理，是否要允许"部分成功"的批次语义待定。

- `apps/server/src/modules/services/querying.py`
  - 复杂搜索、筛选、排序和分页尚未实现。

- `apps/server/src/modules/services/users.py`
  - 真正的认证系统、会话管理和持久化权限体系尚未实现。

- `apps/server/src/modules/services/publishing.py`、`moderation.py`、`comments.py`
  - 目前只有预先准备好的权限校验代码，业务主体尚未实现。

- `apps/server/src/bootstrap.py`
  - 跨服务的事务编排和更完善的（尤其涉及多服务协作的）服务生命周期管理尚未实现。

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
