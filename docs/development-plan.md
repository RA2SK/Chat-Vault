# 项目开发台账

## 一、更新日志

### 2026-09-19（Web API 落地与共享连接并发修复）

- 新增 `api/schemas.py`：请求与响应模型。响应模型刻意不复用领域模型，而是逐字段声明，`ConversationSummaryResponse` 同时提供 `from_view()` 与 `from_model()` 两个构造入口，前者用于列表查询，后者用于发布状态切换——发布接口返回的是领域模型 `Conversation`，直接序列化会把 `source_archive`、`source_entry`、`import_batch_id` 这些内部字段泄露出去。`MarkCreateRequest` 只带 `mark_type`，消息标识由路径给出，避免路径与请求体两处都能指定同一个值而产生分歧。
- 新增 `api/dependencies.py`：依赖装配的唯一入口。`get_current_user()` 从 `X-Chat-Vault-User` 请求头取用户名，再经 `user_service.get_by_username()` 解析成真实的 `UserView`。这是当前阶段（程序只在本地运行、调用方就是部署者本人）的临时身份来源，刻意不做成"开发模式管理员后门"：后门会绕过用户表，使 `created_by` 指向不存在的用户，将来接入真正的认证时还要专门拆掉。真正的认证落地时只需要替换这个函数的函数体，签名和全部调用点都不用动。
- 新增 `api/routes.py`：13 个端点，统一挂在 `APIRouter(prefix="/api")` 下。公开读取一律走 `PublicationServiceContract`，不碰 `QueryingServiceContract`，因为后者不做可见性判断。`GET /api/conversations/{id}` 对"不存在"和"未发布"都返回 404（服务层已把两者统一收敛为 `None`），未发布的标题因此无法被枚举。`GET /api/conversations/{id}/comments` 先调用 `get_conversation_for_view()` 确认可见，再调用评论聚合查询，否则会泄露未发布对话下的评论。导入端点接收文件系统路径而不是上传文件，因为 `python-multipart` 尚未安装，`UploadFile` 不可用。
- `main.py` 挂载路由：`include_router(router)` 放在 `register_exception_handlers()` 之前。
- 新增 `MessageKey.LOGIN_FAILED`：`authenticate()` 认证失败时返回 `None` 而不是抛异常，此前没有"用户名或密码不正确"这条文案可用。
- 把导入器解析函数上提到 `modules/adapters/__init__.py`：新增 `resolve_importer()` 与 `detect_importer()`，`cli.py` 与 `api/routes.py` 共用同一份实现，`cli.py` 里的两个本地副本随之删除。`detect_importer()` 增加了路径存在性预检，否则文件不存在会被误判成格式不匹配。
- `CommentServiceContract.create()` 的入参由拆开的四个参数改为整体传入 `CommentSubmission`：Web 层的请求模型和命令行层的参数解析各自转换成本形状后走同一条路径，新增字段时不必再改调用签名。
- `ModerationServiceContract.list_marks()` 增加当前用户参数并补上管理员校验：此前任何调用方都能读到管理员标记。
- 修复共享数据库连接的并发缺陷（`modules/repositories/database.py`）。连接在 lifespan 所在线程创建，而同步路由由 FastAPI 的线程池执行，因此同一个连接必然被多个线程使用，暴露出两个真实故障：
  - 一个线程的 `commit()` 会把另一个线程尚未完成的事务一并提交，回滚同理。实测两个线程交错执行时，本该回滚的写入留在了库里。修复方式是让 `transaction()` 在整个事务期间持有连接锁。
  - 一个线程的 `commit()` 会重置另一个线程尚未读完的游标，使 `fetchone()` 返回 `None` 或返回字段为空的残缺行，并发执行语句还会直接抛 `InterfaceError`。这个故障在真实压测中表现为 500（`ValueError: Invalid isoformat string: ''`，读到了空的时间戳字段）和偶发的 401（用户查询读到残缺行，被当成用户不存在）。只在 `execute()` 上加锁挡不住它，因为 `connection.execute(...).fetchone()` 的 `fetchone()` 发生在锁之外。修复方式是新增 `_MaterializedCursor`，在 `execute()` 持锁期间就把结果一次性取出并缓存，之后所有 `fetch` 只读缓存，于是整条语句成为原子操作，仓储代码无需任何改动。
  - 连接改用 `check_same_thread=False` 并装配 `_LockedConnection`。锁是模块级可重入锁而不是按连接分锁：`sqlite3.Connection` 既不支持弱引用也不允许附加属性，按连接登记锁需要额外的生命周期管理，而本程序同时只使用一个连接。
- 新增 `tests/test_api.py`（27 项）与两项并发回归测试：`test_transaction_rollback_is_not_swallowed_by_other_thread` 与 `test_concurrent_commit_does_not_reset_in_flight_cursor`。两项都验证过在移除修复后确实失败。
- 端到端验证：用真实 uvicorn 服务跑通全部 13 个端点，并用 16 并发、40 次评论写入加 40 次对话读取的压测确认修复前出现的 500 与 401 全部消失（连续三轮均为 40×201 + 40×200）。
- 全量测试 150 项通过；`ruff` 无新增问题（剩余 12 项 `E501` 为既有问题）；`pyright` 在 `basic` 模式下 0 错误。

### 2026-09-18（异常体系、文本集中管理与入口文件）

- 建立业务异常体系 `core/exceptions.py`：新增基类 `ChatVaultError`，以及 `ValidationError`(400)、`NotFoundError`(404)、`ConflictError`(409)、`PermissionDeniedError`(403)、`NotAuthenticatedError`(401)、`ImportFailedError`(422)、`PersistenceError`(500) 七个具体类型。每个具体类型都额外继承一个对应的内置异常（例如 `ValidationError` 同时继承 `ValueError`、`NotFoundError` 同时继承 `LookupError`、`NotAuthenticatedError` 与 `PermissionDeniedError` 同时继承 `PermissionError`），这样既有调用点的 `except ValueError` / `except LookupError` / `except PermissionError` 写法继续有效，异常分类也不再靠字符串判断。刻意没有定义 `ImportError` 这个名字，它会与内置的同名异常混淆。
- 新增 `core/messages.py` 集中管理所有面向用户的文本：`MessageKey(str, Enum)` 定义语义键，`TEXTS` 给出每个键的模板，`render(key, **params)` 负责填充。键按语义而非代码位置命名（`CONVERSATION_NOT_FOUND`、`IMPORT_FORMAT_MISMATCH`），因为同一个函数里有十几条不同的校验失败，用“模块_文件_类_函数_报错类型”这种按位置取名的方案既无法用类型检查保护，又会出现一个函数共用一把键的粒度错配。`render()` 在调用方多传参数时直接抛 `TypeError`，避免 `str.format` 静默忽略多余参数导致文案停留在旧版本。
- 迁移全部 48 处 `raise` 调用点：`services/` 与 `repositories/` 下的 9 个文件改为抛出业务异常并携带消息键与参数，`adapters/preprocess.py` 的 4 处 `ValueError` 改为 `ValidationError`（其中一处 `TypeError` 属于调用方用错类型，保留内置异常）。`repositories/database.py` 的连接与建表故障统一包成 `PersistenceError`，并用 `raise ... from exc` 保留原始堆栈。
- 异常只描述、不翻译：`core` 层不出现 HTTP 状态码，状态码映射只存在于 `api/exception_handlers.py`，退出码映射只存在于 `cli.py`。两处都用精确类型查表而不是 `isinstance` 判断，漏配一项会直接暴露出来，而不会悄悄退回到父类的取值。
- 新增 `api/exception_handlers.py`：`register_exception_handlers()` 同时注册 `ChatVaultError` 与兜底的 `Exception` 处理器。响应体固定为 `{"error": {"key": ..., "message": ...}}`，前端按稳定的 `key` 分支，不依赖会变的文案。4xx 记 `info`，5xx 记 `warning` 并带堆栈；兜底处理器是全应用唯一一处 `logger.exception`，对外只返回“服务器内部错误”，不泄露内部文本。
- 新增 `utils/logging.py`：`configure_logging(level, *, json_output=False)` 提供文本与单行 JSON 两种格式，带毫秒级 UTC 时间戳、异常堆栈与额外字段。配置函数幂等，只移除自己安装的处理器，保留宿主进程（例如 pytest）已有的处理器；字段名中含有 `password`、`secret`、`token`、`authorization`、`credential` 等片段的额外字段会被替换成 `***`。文本目录与日志系统刻意分开：前者是给用户看的话，后者是给开发者看的记录，两者受众、生命周期和改动力度都不同。
- 新增 `main.py`：ASGI 入口。`create_app()` 先配置日志再组装应用，因此 `uvicorn main:app` 这条生产路径不需要额外配置；`lifespan` 创建服务容器放入 `application.state.container`，并在应用停止时回滚未提交事务、关闭连接；`_boot_admin()` 读取 `CHAT_VAULT_ADMIN_USERNAME` 与 `CHAT_VAULT_ADMIN_PASSWORD`，两者齐全且库中无管理员时自动建一名，凭据缺失则静默跳过（这是“不启用自动初始化”的开关），用户名被占用只记一条错误并继续启动——自动初始化是为了方便，不该成为服务起不来的原因。环境变量：`CHAT_VAULT_DATABASE_PATH`、`CHAT_VAULT_ADMIN_USERNAME`、`CHAT_VAULT_ADMIN_PASSWORD`、`CHAT_VAULT_LOG_LEVEL`、`CHAT_VAULT_LOG_JSON`。
- 新增 `cli.py`：命令行入口，含 `import`、`conversations`、`show`、`comments`、`create-admin` 五个子命令。结果走标准输出，日志与错误走标准错误，便于把结果直接管道给下一个命令。退出码约定为 0 成功、1 未预期异常、2 用法错误、3 输入不合法、4 不存在、5 冲突、6 需要登录、7 权限不足、8 持久化故障。管理员密码只从环境变量或交互式输入读取，刻意不提供 `--password` 参数，因为它会留在 shell 历史记录和进程列表里。容器创建也放在 `try` 之内，这样建库失败同样走统一的报错分支。
- 新增 `tests/test_messages_and_exceptions.py`：用 `ast` 扫描全部源码，校验文本目录与实际抛出的消息键双向一致（没有缺文案的键，也没有没人用的死键），并校验每个键的占位符与调用点传入的参数名吻合，以及异常的双继承关系确实成立。
- 更新 8 个接口契约文件的文档串，把 `Raises:` 段落里的内置异常名改为对应的业务异常名。契约只描述会抛什么，转发由上层负责。
- 全量测试 70 项通过；`ruff` 无新增问题（剩余 12 项 `E501` 为既有问题）；`pyright` 在 `basic` 模式下 0 错误。

### 2026-09-17（契约边界收窄与展示视图落地）

- 用户服务对外返回值统一收窄为 `UserView`：`register()`、`register_admin()`、`get()`、`get_by_username()` 返回视图，`authenticate()` 返回 `UserView | None`。新增 `UserView.from_model()` 逐字段复制允许暴露的字段，刻意不用 `dataclasses.asdict`，这样 `User` 以后新增字段时不会因为疏忽被自动带出去。
- `password_hash` 不再穿过契约边界：新增私有方法 `_authenticate_user()` 返回领域模型，只在认证成功后签发会话、改密前确认旧密码这类内部流程中使用。
- `change_password()` 入参由 `User` 改为 `UserView`：实现内部按视图中的 id 重新取回领域模型，调用方无法通过持有 `User` 绕过校验。空新密码抛 `ValueError`，用户已不存在抛 `LookupError`，旧密码不正确抛 `PermissionError`。
- 权限判断函数 `is_admin()`、`is_authenticated()`、`require_admin()`、`require_authenticated()` 的入参由 `User | None` 放宽为 `UserView | None`，因为判断权限只需要 `id` 和 `role`。`comments.py`、`moderation.py`、`publishing.py` 与契约文件的当前用户类型同步改为 `UserView | None`。
- 发布服务真正产出展示视图：新增模块级映射函数 `to_published_message_view()`、`to_published_conversation_view()`、`to_published_conversation_summary()` 与私有 `_current_branch()`，剥离策略放在发布用例内部而不是共享工具里，因为"哪些字段对外可见"是发布场景的规则。
- `PublicationServiceContract.list_for_view()` 返回类型由 `list[Conversation]` 收窄为 `list[PublishedConversationSummary]`（新增的列表项形状），`get_conversation_for_view()` 由 `ConversationDetail | None` 收窄为 `PublishedConversationView | None`。展示输出剥离 `thinking`、`edited_by`、`source_archive`、`source_entry`、`source_type`、`is_published`、`import_batch_id` 和 `branches`。
- 展示按"当前链"展开：优先取 `is_current` 的分支，没有标记时取消息最多的一条，避免对话因为元数据缺失显示为空。刻意不合并多条分支，因为每条消息的 `position` 在所属分支内编号，合并会产生重复序号和互相冲突的内容。
- 修复可见性不对称：此前"对话不存在"返回 `None` 而"存在但未发布"抛 `PermissionError`，两者可区分，未发布的对话标题因此会被枚举出来。现在两种情况统一返回 `None`。
- 删除 `core/__init__.py` 的惰性再导出（`__getattr__`）：`ConversationDetail` 是一次查询调用的产出形状，属于接口层；服务实现和容器不是核心层概念。三个名字都没有调用方，因此无需改动调用点。此改动同时消除了 4 条 pyright 的 `reportUnsupportedDunderAll` 警告。
- 新增 `tests/test_boundary_stripping.py`，覆盖用户服务返回值不含 `password_hash`、`User` 模型字段变化时提醒是否暴露、改密的三条失败路径、列表项与详情视图不泄露内部字段、展示只展开当前链、附件以 `source_ref` 传出、未发布对话对普通用户与不存在对话返回同一个结果。

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
- `apps/server/src/modules/repositories/database.py`：完成 SQLite 连接、外键设置、数据库初始化和事务管理。连接装配为 `_LockedConnection`，语句执行返回 `_MaterializedCursor`，两者共同保证多线程共用同一个连接时的原子性，详见更新日志。
- `apps/server/src/modules/repositories/schema.sql`：完成数据库表、字段、索引和外键约束，暂不持久化 `MessageRevision`。
- `apps/server/src/modules/repositories/mappings.py`：完成数据库行与核心模型之间的转换，集中持有列名知识以及时间、校验值的双向转换。
- `apps/server/src/modules/repositories/conversations.py`：完成 `ConversationRepository` 和 `BranchRepository`。
- `apps/server/src/modules/repositories/messages.py`：完成 `MessageRepository` 和 `AttachmentRepository`。
- `apps/server/src/modules/repositories/imports.py`：完成 `ImportBatchRepository`。
- `apps/server/src/modules/repositories/users.py`：完成 `UserRepository`。
- `apps/server/src/modules/repositories/comments.py`：完成 `CommentRepository`。
- `apps/server/src/modules/repositories/moderation.py`：完成 `AdminMarkRepository`。
- `apps/server/src/modules/repositories/__init__.py`：完成 8 个仓储类的统一导出。
- `apps/server/src/api/exception_handlers.py`：完成业务异常到 HTTP 状态码的映射与统一错误响应体。
- `apps/server/src/api/schemas.py`：完成请求与响应模型，响应模型逐字段声明，不直接序列化领域模型。
- `apps/server/src/api/dependencies.py`：完成依赖装配，`get_current_user()` 是当前阶段唯一的身份来源。
- `apps/server/src/api/routes.py`：完成 13 个端点，公开读取一律走发布服务，不碰查询服务。
- `apps/server/src/bootstrap.py`：完成数据库连接、8 个仓储和两个业务服务的依赖组装。服务级事务边界已在各服务内声明，跨服务的事务编排和更完整的生命周期管理尚未实现。

### 已部分完成

- `apps/server/src/modules/services/importing.py`：已完成适配器调用、解析结果处理、基础校验、幂等保存（含按文件内容摘要的重复导入检测）、`source_archive` 归档信息和导入批次统计；每个导入操作的事务边界已落地，更复杂的错误恢复和更多边界规则尚未实现。
- `apps/server/src/modules/services/querying.py`：已完成对话列表、已发布对话列表、对话详情以及分支、消息和附件的基础查询；复杂搜索、筛选、排序和分页尚未实现。
- `apps/server/src/modules/services/users.py`：已完成权限判断、普通用户注册、管理员注册、`has_admin` 检查、认证与改密；用户信息维护和会话管理尚未实现。对外返回值已统一收窄为 `UserView`，需要读取 `password_hash` 的认证与改密流程改为在实现内部取回领域模型，密码散列不再穿过契约边界。
- `apps/server/src/modules/services/publishing.py`：已完成发布权限判断、发布状态切换，以及展示视图的产出：`list_for_view` 返回 `PublishedConversationSummary`，`get_conversation_for_view` 返回 `PublishedConversationView`，两者均已剥离思考内容、备份组织方式、导入批次和编辑者等内部字段；展示按当前链展开，不合并历史分支。未发布对话对非管理员统一返回 `None`。
- `apps/server/src/modules/services/moderation.py`：只有预先准备好的最小管理权限判断；管理员编辑、标记和维护流程尚未实现。
- `apps/server/src/modules/services/comments.py`：已完成评论的创建、按对话查询、按消息查询、对话级聚合查询和软删除；评论编辑按设计不提供，修改意见只能删除后重发。
- `apps/server/src/core/__init__.py`：仅完成领域模型的公共导出。`ConversationDetail` 是查询调用的结果形状，已归于接口层；服务实现和容器不再从本包惰性再导出，需要时直接从各自模块导入。
- `apps/server/src/modules/interfaces/`：契约层已完整建立。`repositories_intf.py`、`importing_intf.py`、`querying_intf.py`、`publishing_intf.py`、`moderation_intf.py`、`comments_intf.py`、`users_intf.py`、`exporting_intf.py` 与 `__init__.py` 均已写入契约；各契约的输入输出形状均已与实际实现一致，`PublicationServiceContract` 声明 `PublishedConversationView`，`UserServiceContract` 声明 `UserView`；`exporting_intf.py` 只声明了形状，没有任何实现。

### 未开工

- `apps/server/src/modules/interfaces/exporting_intf.py`：内容重新打包契约已声明形状，输出端实现、Web 数据提交和落盘编排尚未开始。
- `apps/server/src/utils/hashing.py`：文件已建立，校验和计算尚未开始。
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
  - 真正的认证系统、会话管理和持久化权限体系尚未实现。当前 `api/dependencies.py` 从请求头取用户名作为身份来源，这是程序只在本地运行阶段的临时方案，接入真正的认证时只需替换 `get_current_user()` 的函数体。

- `apps/server/src/modules/services/publishing.py`、`moderation.py`、`comments.py`
  - 权限校验已接入全部对外入口；更细粒度的权限规则（例如按对话授权）尚未实现。

- `apps/server/src/bootstrap.py`
  - 跨服务的事务编排和更完善的（尤其涉及多服务协作的）服务生命周期管理尚未实现。

- `apps/server/src/core/__init__.py`
  - 更复杂的业务初始化和导出控制尚未实现。

- `apps/server/src/modules/repositories/schema.sql`
  - 当前为基础版本；未来需要根据 `core/models/` 的字段、关系和约束变化继续完善。

- `apps/server/src/modules/repositories/database.py`
  - 基础连接和事务功能已完成；未来可能根据数据库迁移和模型演化需求扩展。
  - 当前用一把模块级可重入锁串行化全部数据库访问，这对单连接设计是正确且廉价的；若将来改为连接池，锁需要改为按连接持有，届时必须显式管理生命周期，因为 `sqlite3.Connection` 既不支持弱引用也不允许附加属性。
  - `bootstrap.py` 的 `ServiceContainer.close()` 内联了回滚与关闭，没有调用 `close_connection()`；若将来引入按连接的锁登记，这里需要同步更新。

- `apps/server/src/modules/repositories/`
  - 基础 Repository 已完成；未来需要根据 `core/models/` 的完善同步增加或调整持久化字段、关系和查询接口；仓储层收到的修改需求也在累积，需要安排一次统一调整。

### 不属于单个文件的更新内容

- 完成 Web API 与前端之间的数据接口：服务端 13 个端点已落地，前端尚未接入。
- 完成前端对话展示、Markdown 模拟渲染、评论回传和未来下载功能。
- 适配器、导入服务、存储层和输出层尚未接入统一日志接口：`utils/logging.py` 已提供格式化与脱敏能力，但各层目前仍只有极少量日志调用点，需要随业务补齐。
- 仓储层已对外统一以 `source_id` 标识内容对象，数据库主键不再离开持久化层；后续新增查询接口时需要继续保持这一约定。
