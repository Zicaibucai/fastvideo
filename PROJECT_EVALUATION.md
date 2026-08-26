# FastVideo 建筑工程 AI 投标视频平台 — 全面评价报告

> 评价日期：2026-08-26 · 初始基线评价；本轮修复复核：全量测试 228 项通过

---

## 一、项目概况

| 维度 | 数据 |
|---|---|
| 定位 | 建筑工程投标视频自动化生产平台：上传招标文件/施组/模型截图 → 解说词拆解 → 画面生成 → AI 配音 → 多分段视频合成 → 导出 16:9 1080P 投标视频 |
| 后端 | FastAPI + SQLAlchemy + Alembic + Celery/Redis（可降级同步），113 个 Python 文件，约 29,100 行 |
| 前端 | React 18 + TypeScript + Vite 6 + AntD 5，34 个源文件，约 14,300 行，17 个页面 |
| 测试 | 后端测试现为 **228 项全部通过**；前端已加入类型检查、路由懒加载与构建校验，仍缺少浏览器级自动化测试 |
| 数据库 | 27+ 张表（9 个核心实体起步，7 个阶段逐步扩展），19 个线性 Alembic 迁移 |
| AI 接入 | LLM（DeepSeek/Kimi）、图生图（Seedream 4.5）、图生视频（Seedance 2.0 / MiniMax H3）、TTS（火山豆包 2.0）、OCR（Tesseract），全部走适配器 + 能力矩阵 + Mock 降级 |
| 部署 | Docker Compose 全家桶（postgres/redis/minio/api/worker/frontend）+ 本地降级模式（SQLite + 同步任务） |
| 文档 | README（24KB）、task_plan.md（7 阶段计划全勾选完成）、阶段交付文档、.env.example（5053 字节，键全） |

**总体结论：以实习生限时项目衡量，这是一份完成度和工程质量都明显超出预期的交付物。** 架构分层干净、AI 适配器抽象执行到位、安全意识（Cookie 鉴权、上传魔数校验、密钥加密落库、路径穿越防护）甚至超过一些正式项目。当前主要短板集中在几个超长“上帝模块/巨石组件”的可维护性、测试隔离与异步覆盖、时间/状态类型治理，以及 Git 版本管理几乎形同虚设。

### 本轮修复复核

已落地的修复包括：Celery Worker 在每个任务前从数据库刷新 AI 配置；Provider Key 以 Fernet 加密落库并兼容旧明文迁移；Alembic 使用绝对路径且迁移失败拒绝启动；项目级幂等键增加数据库唯一约束并清理历史重复值；配音、截图渲染、AI 视频版本号增加数据库唯一约束并改为基于历史最大值递增（含软删除记录）；补全导出、合成、分段和配音任务重试映射，未知任务不再静默卡在 queued；登录限流支持 Redis 跨进程共享并带有内存降级；Cookie 写请求增加来源校验；GET 项目详情不再写入访问时间，改由显式 `/enter` 端点；文件前缀默认拒绝；前端路由拆分懒加载、轮询定时器统一清理；通知中心在后台标签页暂停并将轮询降为 10 秒；“需调整”配音筛选改为读取正式版本状态；补齐 CI、Ruff 正确性检查、Docker 构建上下文排除和第三方素材发布审计。

仍需在正式发布前由项目负责人处理的事项：第三方样片素材的授权证明（见 `THIRD_PARTY_ASSETS.md`）、前端浏览器级测试、异步 Celery 真 Redis 环境测试，以及提交历史和运行目录的归档清理。测试基础设施已改为每次 pytest 进程独立临时数据库/存储目录，但模块内 fixture 的进一步细粒度隔离仍可继续推进。

---

## 二、突出亮点（超出预期的部分）

### 1. 架构分层与适配器模式执行到位
路由薄（只做鉴权/校验）、业务逻辑下沉 `services/`、AI 调用一律走 `adapters/`。适配器基类只约定 `is_available()`/`capabilities()`，业务用**能力矩阵做硬性校验**而非 try/except 探测；关键场景明确**禁止静默降级**——`factory.py:328` 未配 Key 返回 `None` 报错，`video_gen_service.py:684` 首尾帧模式缺帧直接报错而非降级为普通图生视频。这种"宁可报错不可静默出错"的设计取向非常成熟。

### 2. 领域建模体现真实业务思考，而非 CRUD 直译
- 投标关键参数（面积/工期/日期/招标人）带 `*_source_page` **来源页码溯源**，从模型层防止 AI 编造（`project.py:30-37`）；
- `AudioVersion` 保存文本快照/参数快照/授权快照 + `is_stale` 标记解说词变更后的失效版本；
- 分镜跨重生成用 `is_active + revision` 归档而非物理删除，保留素材绑定追溯；
- 配音音色授权状态机（unknown/pending/rejected/expired/mock_only）直接拦截正式导出。

### 3. 运行时 AI 配置层是亮点中的亮点
API Key 用 Fernet 加密落库、接口只回显末四位、用配置签名做 API/Celery 跨进程变更检测、保存后主动 `cache_clear` 工厂缓存、Celery `task_prerun` 钩子里刷新（`ai_configuration.py`）。这是真正想清楚了多进程一致性的做法。

### 4. 基础设施细节扎实
SQLite 每连接开外键使行为与 PostgreSQL 一致；生产配置 fail-fast（DEBUG/弱密钥/默认管理员密码全拦截，`config.py:179`）；迁移失败拒绝启动；同步降级时把分钟级任务扔本地线程池而非阻塞请求线程（说明真踩过坑）；全库 0 处 `shell=True`、0 处 f-string SQL，FFmpeg 全部参数数组 + 过滤器脚本文件防注入。

### 5. 注释质量高
几乎每个非显然决策都有"为什么这么做"的记录，且有一整套"修复过的坑"的知识沉淀（ReDoS 防护、中文数字朗读、SQLAlchemy JSON 原地修改、FastAPI 204 注解等）。这对可维护性是很大加分。

### 6. 前端同样有工程化意识
axios 统一封装 + 401 拦截 + FastAPI 错误中文化；HttpOnly Cookie 鉴权替代 localStorage JWT 并注释说明理由；分片上传带 SHA-256 校验；任务提交带幂等键；草稿持久化带版本号和防抖；侧边栏最长前缀匹配高亮。

---

## 三、主要问题（按严重程度排序）

以下条目是初始基线审查记录；已修复项目请以本节上方“本轮修复复核”为准，未列入修复清单的条目仍属于技术债。

### 🔴 高：会在生产中真实发作的正确性缺陷

1. **`backend/app/tasks/video_gen.py:45` 真实 bug**：`video_gen_job_sync = _execute` 覆盖了第 20 行刚定义的、符合 params 字典约定的同名函数，前者成死代码；若 `task_runner.dispatch` 以 `sync_func(task.params)` 调用会直接 TypeError。
2. **重试路由静默卡死**：`api/v1/tasks.py:89-99` 的 retry mapping 只覆盖 5 种 task_type，缺 `compose_video`/`export`；状态已被重置为 `queued` 但不分发——这两类任务重试后永远卡在 queued，无任何提示。
3. **幂等键与版本号无数据库约束**：`render_jobs.idempotency_key` 只有普通索引；配音/视频版本号用 `count()+1` 且排除软删除（删 V3 后下一个又编 V3，并发双击也撞号）。双击/重试/并发场景会产生重复任务或重号。全库仅 2 处 unique 约束。
4. **前端定时器泄漏**：`Video.tsx:209-253` 的 `pollSegmentRender`/`pollTask` 在事件处理器里 `setInterval`，组件卸载时不清理，离开页面后继续打 API 并 setState；`TaskStatus.tsx:88` 同问题。
5. **通知中心轮询过重**：`ProjectNotificationCenter.tsx` 每 3 秒并行打 6 个接口，挂在每个项目页面上，页面空闲也在全量轮询（后端压力 ≈ 在线项目页数 × 2 QPS）。

### 🟡 中：可维护性的最大单点

6. **上帝模块/巨石组件**：
   - 后端 `narration_engine.py` **2062 行**、60+ 函数；`video_gen_service.py` 1521 行（其中 `generate_prompt_master` 单函数 351 行）；`voice_service.py` 单函数 203 行。
   - 前端 `AiVideo.tsx` **1867 行 / 46 个 useState / 160 处内联样式 / 约 700 行 JSX**；`VideoTemplateCreator.tsx` 1313 行；`Storyboard.tsx` 1147 行。全项目 `useCallback` 仅 4 处、`React.memo` 为 0。
   - 功能堆进单文件的速度超过了拆分速度——这是当前可维护性的最大杠杆点。
7. **测试盲区**：所有测试共享一个 `/tmp` 数据库、零隔离、依赖默认管理员密码（换密码即全红）、无法并行；Celery 异步路径从未被测（conftest 强制 `USE_CELERY=false`）；无并发/幂等测试；跨租户负向测试不成体系（仅文件读取覆盖）。前端零测试框架。
8. **类型安全边界失守**：tsconfig 开了 strict，但全项目 107 处 any，`api/index.ts` 25 处 `Record<string, any>` 请求 payload——响应类型很认真、请求类型放弃了，重构后端字段名时前端拿不到编译保护。`types.ts` 里 `created_at?: any` 属笔误级松懈。

### 🟠 中低：安全与规范

9. **`files.py` 默认开放而非默认拒绝**：只对两种 key 前缀做租户校验，未来新增存储前缀会天然处于"登录即可读"状态，应改白名单默认 404。路径穿越防护本身做得很好（双重 normpath + root 校验）。
10. **Cookie 认证无 CSRF token**：仅靠 `samesite="lax"` 缓解；且 `GET /projects/{id}` 有写副作用（更新 `last_entered_at`），违反 HTTP 语义且放大 CSRF 面，应拆成显式 `POST .../enter`。
11. **时间戳类型混乱**：部分模型用 `String(32)` + `time.strftime`（本地时区）存时间，部分用 `DateTime(timezone=True)` + UTC——同一系统两种时间表示，字符串时间无法索引/排序/跨时区比较。
12. **状态字段全部裸字符串**：job/shot/task 的 status 无 Enum/CheckConstraint，拼写错误只能靠测试兜。

### 🔵 低：重复与死代码

13. 重复代码：后端 `_create_document` 与 `upload_document` 主体几乎逐行重复；factory 四个 `get_*_adapter` 分支是同样板；测试文件各自复制 login fixture。前端 blob 下载重复 4 处（抽了公共函数却没改旧三处）；任务类型中文标签两处维护且 key 集合不一致。
14. 死代码/半成品：历史基线中的 `VoiceWorkspace.tsx:144` 无条件筛选和 3 处无效 eslint-disable 注释已处理；`vite.config.verify.mjs`、`vite.config.e2e.mjs` 等一次性脚本仍保留，待确认是否需要纳入正式测试流程后再归档或删除。

---

## 四、工程规范与仓库卫生（最薄弱环节）

这是项目最大的问题区域，与代码质量形成鲜明反差：

1. **Git 形同虚设**：仓库只有 **1 个 commit**（2026-08-20 的 "Initial commit"），之后 6 天的开发（145 个文件变更，其中 49 个新文件）**全部未提交**。没有分支、没有提交历史、没有增量备份——一旦误删或改坏，无法回滚到任何中间状态。建议立即提交，并养成"每完成一个小功能就 commit"的习惯。
2. **磁盘杂物 ~2.4GB**：`fastvideo.zip`（60MB）、`zitG1nIE`（436KB 不明文件）、`fastvideo_share.zip`（0 字节空文件）、`app.db`（832KB 运行库）散落在根目录；`openevai_img2video/` 335MB 抓取素材；`backend/data/` 1.7GB 运行时数据。虽然 `.gitignore` 已正确排除它们，但工作目录本身该清理归档。
3. **.env 管理良好**：真实密钥未入库（git 只跟踪 `.env.example`），12 个含 KEY/SECRET/PASSWORD 的项都安全。但注意 `.env` 比 `.env.example` **少 19 个键**（如 `POSTGRES_PASSWORD`、`MINIO_ROOT_PASSWORD`、`AUTH_COOKIE_SECURE`）——docker-compose 里这些键是 `:?` 必填的，意味着当前 `.env` 直接 `docker compose up` 会启动失败，需补齐。
4. **沙箱遗留环境债**：`backend/.venv` 解释器指向已失效的旧会话路径（损坏）；openai 包内部 import 损坏（httpx2），导致 3 个测试失败。建议在本机重建 venv 一劳永逸。
5. **依赖版本健康**：FastAPI 0.115 / Pydantic 2.10 / Celery 5.4 等均为合理新版且精确锁定；前端依赖极简无冗余。

---

## 五、分项评分

| 维度 | 评分 | 说明 |
|---|---|---|
| 架构设计 | ★★★★★ | 分层干净、适配器抽象、能力矩阵、双模任务队列，超出实习生水准 |
| 领域建模 | ★★★★★ | 来源页码溯源、版本快照、授权状态机，真正理解业务 |
| 后端代码质量 | ★★★☆☆ | 细节扎实，但上帝模块 + 幂等/重试缺陷 + 事务边界模糊 |
| 前端代码质量 | ★★★☆☆ | API 层优秀，页面层巨石组件 + 定时器泄漏 + 类型边界失守 |
| 安全性 | ★★★★☆ | 上传/路径/密钥/注入防护全面；扣分在 files.py 默认开放、CSRF、GET 写副作用 |
| 测试 | ★★★★☆ | 后端 228 项分层测试且持续写回归；仍需补充 Celery 真异步、并发幂等和前端浏览器测试 |
| 文档 | ★★★★★ | README/task_plan/阶段交付文档齐全，"踩坑记录"尤为珍贵 |
| 工程规范 | ★★☆☆☆ | Git 单 commit + 145 个未提交变更 + 目录杂物，是最大短板 |
| 部署 | ★★★★☆ | Docker Compose 完整 + 本地降级模式贴心；.env 键缺失需补 |

**综合：★★★★（4/5）** —— 一个架构意识出色、业务理解到位、完成度很高的项目；把工程规范和几个正确性缺陷补上，可以达到准生产级。

---

## 六、行动建议（按优先级）

**立即做（本周）**
1. `git add -A && git commit`——把 145 个未提交变更入库，此后每完成一个小功能就提交。
2. 修 `tasks/video_gen.py:45` 的函数覆盖 bug + 补 `tasks.py:89` retry mapping 缺失的 `compose_video`/`export`（不在 mapping 的类型应明确报错而非停在 queued）。
3. 修前端定时器泄漏：`Video.tsx`/`TaskStatus.tsx` 的轮询统一走带卸载清理的模式。
4. 补齐 `.env` 缺失的 19 个键（对照 `.env.example`）。

**上线前做**
5. 给 `render_jobs.idempotency_key`、配音/视频版本号加唯一约束，版本号改 `max()+1`（不排除软删除）。
6. `files.py` 改默认拒绝白名单；`GET /projects/{id}` 的写副作用拆为 `POST .../enter`。
7. 通知中心轮询降载（空闲降频 3s→15s、页面隐藏暂停，或后端出聚合状态接口）。

**作为技术债排期**
8. 拆 `narration_engine.py`（2062 行）和 `AiVideo.tsx`（1867 行）——可维护性最大杠杆。
9. 测试基建：conftest 加事务回滚 fixture、补跨租户参数化负向测试和幂等并发测试、前端引入 vitest。
10. 统一时间戳为 `DateTime(timezone=True)`、状态字段 Enum 化、引入真正的 ESLint。

---

*评审方法说明：本报告基于初始基线的后端代码评审，以及修复后的实际全量测试（228 passed）、前端类型检查/生产构建、Ruff 正确性检查、Alembic 全链路迁移和 Docker Compose 配置校验。历史问题清单保留用于追踪，当前状态以“本轮修复复核”和仓库实际代码为准。*
