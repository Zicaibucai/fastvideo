# 建筑工程AI投标视频平台

一套面向建筑施工企业的 **AI 投标视频自动化平台**。上传招标文件、施工组织设计、模型截图与项目素材，系统自动完成解说词拆解、画面生成、AI 配音、多分段视频合成与素材复用，最终导出 **16:9、1080P** 的工程投标视频。

![stack](https://img.shields.io/badge/前端-React%20%2B%20TypeScript%20%2B%20Vite%20%2B%20AntD-blue)
![stack](https://img.shields.io/badge/后端-FastAPI%20%2B%20PostgreSQL-green)
![stack](https://img.shields.io/badge/队列-Redis%20%2B%20Celery-orange)
![stack](https://img.shields.io/badge/AI-Adapter%20%2B%20Mock%20模式-8A2BE2)

---

## ✨ 功能特性

- **招标资料管理**：上传招标文件 / 评分办法 / 施工组织设计 / 项目概况 / 进度计划 / 专项方案 / 企业资信等，支持 PDF / DOCX / TXT，SHA-256 去重，普通上传单文件 30MB 上限；更大文件使用分片上传。
- **精准文档解析**：按页解析 PDF（pdfplumber）/ DOCX / TXT，提取表格与目录结构；扫描页自动检测并调用 OCR（Mock / Tesseract），OCR 失败不阻断解析。
- **工程参数台账**：自动提取 20 类关键参数（面积/工期/日期/高度/层数/金额/评分项等），每个参数保存来源页码与原文；不同来源冲突时标记 conflict 不自动选择，支持人工确认/驳回/修改。
- **评分点覆盖**：从评分办法提取评分点与分值，统计每个评分点被哪些分镜覆盖。
- **解说词智能拆解**：AI 根据已确认事实与评分点生成 3～5 分钟解说词，自动拆分为 10+ 可编辑分镜，每个分镜带来源引用与事实校验状态；未验证数据不写入正式解说词。
- **画面制作（模型截图渲染）**：上传 Revit/Navisworks/SketchUp 等模型截图，选择 12 种渲染预设，配置画面比例/结构保持强度/生成数量，异步 AI 渲染；支持局部重绘（遮罩）、16:9 扩图、清晰度增强。
- **版本管理与分镜绑定**：原图保留为 V0，生成结果从 V1 起多版本保存；结构一致性辅助检查（SSIM/边缘重合）；选择版本绑定到分镜画面，自动加入素材库，保留来源链与历史选择；更换画面标记相关视频段需重建。
- **AI 安全约束**：所有 AI 生成图带免责声明（"AI渲染图仅用于视觉表达"）；系统级结构保持提示不可删除；检测到改变楼层/轮廓/道路等冲突请求默认拦截；结构一致性检测标注为"辅助检查"。
- **分镜编辑器**：列表/时间轴视图、拖拽排序持久化、新增/复制/删除、重新生成、历史版本恢复、来源跳转、评分点覆盖提示。
- **配音制作（Phase 4）**：企业配音模板（正式稳重/沉稳大气/科技专业/亲和自然等 8 种风格）、音色授权管理、试听；中文朗读规范化（数字/日期/单位/缩写/发音词典）；时长估算与智能适配（≤5% 匹配 / 5~12% 微调 / >12% 需调整解说词）；音频版本管理（V1 起递增、设为正式、恢复历史、软删除）；解说词修改自动标记旧配音/字幕过期；自动生成字幕时间轴与项目级/单条 SRT；导出全部 WAV/MP3/SRT；Mock 音频标记演示提示音。
- **素材库与视频导出**：AI 生成画面/配音/视频，16:9 1080P MP4 导出。
- **多分段视频合成（Phase 5）**：分镜→分段→转场拼接→背景音乐→Logo/片头片尾→1080P H.264 MP4；图片 Ken Burns 动态化、视频素材标准化（循环/裁切）；正式配音混入 + 背景音乐自动压低（ducking）；ASS 中文字幕烧录与独立 UTF-8 SRT；input_hash 缓存（素材变化只重建相关分段）；演示版/正式版导出校验严格区分；导出报告。
- **AI 视频生成（Phase 6/7，Seedance）**：独立「AI 视频生成」页面（`/project/:projectId/ai-video`），图片驱动视频工作流——用户主动选择首帧/尾帧、选择 42 种建筑视频模板、填写独立视频提示词（不引用解说词）、生成独立视频素材。默认 Provider 为 Seedance（火山方舟 Ark），MiniMax 保留但不再默认调用；支持首尾帧（顺序固定 `[first_frame, last_frame]`）、时长/比例/分辨率/随机种子/声音开关（默认关闭）；每次生成保存完整参数快照可复现；结果版本可预览/下载/选为当前。AI 视频结果不绑定解说词分镜，只在「视频工程」中由视频分段选择素材；建筑强约束默认启用，冲突指令（增加楼层/改变轮廓/移动道路/替换主楼）阻止提交。
- **AI 接口全 Mock 可运行**：无 API Key 自动进入 Mock 演示模式，Mock 渲染用 Pillow 生成真实可访问图片，所有页面与流程可完整走通。
- **异步任务队列**：所有耗时 AI 任务经 Celery 异步执行，前端实时展示排队/处理中/成功/失败/重试状态。

## 🧱 技术栈

| 层 | 技术 |
|---|---|
| 前端 | React 18 · TypeScript · Vite · Ant Design 5 · Axios · React Router |
| 后端 | Python 3.11 · FastAPI · SQLAlchemy 2 · Alembic · Pydantic v2 |
| 数据库 | PostgreSQL 16（本地开发可用 SQLite 降级） |
| 队列 | Redis 7 + Celery 5 |
| 文件存储 | 本地存储 + MinIO 兼容 S3 |
| 视频处理 | FFmpeg |
| AI | Adapter 适配器模式：Kimi 文本结构化+多模态 / Seedream 4.5 图生图 / Seedance 2.0 标准档图生视频（火山方舟 Ark）/ 火山豆包语音合成 TTS + Mock |
| 部署 | Docker Compose（postgres / redis / minio / api / worker / frontend） |

## 📁 目录结构

```
fastvideo/
├── backend/
│   ├── app/
│   │   ├── main.py                 # FastAPI 入口
│   │   ├── core/
│   │   │   ├── config.py           # 配置（读取 .env）
│   │   │   ├── database.py         # SQLAlchemy 引擎/会话
│   │   │   ├── exceptions.py       # 统一异常处理
│   │   │   ├── logging.py          # 日志系统
│   │   │   ├── storage.py          # 本地/MinIO 存储抽象
│   │   │   └── security.py         # JWT / 密码哈希
│   │   ├── models/                 # SQLAlchemy 模型
│   │   ├── schemas/                # Pydantic Schema
│   │   ├── api/
│   │   │   ├── deps.py             # 依赖注入
│   │   │   └── v1/                 # v1 路由
│   │   ├── services/               # 业务逻辑
│   │   ├── adapters/               # AI 适配器
│   │   └── tasks/                  # Celery 任务
│   ├── alembic/                    # 数据库迁移
│   ├── tests/                      # pytest 测试
│   └── requirements.txt
├── frontend/
│   ├── src/
│   │   ├── api/                    # API 客户端
│   │   ├── components/             # 通用组件
│   │   ├── pages/                  # 页面
│   │   ├── stores/                 # 状态管理
│   │   └── main.tsx
│   └── package.json
├── docker-compose.yml
├── .env.example
└── README.md
```

## 🚀 快速启动

### 方式一：Docker Compose（推荐）

```bash
cp .env.example .env
# 启动共享/生产环境前，请替换 POSTGRES_PASSWORD、MINIO_ROOT_PASSWORD、SECRET_KEY、ADMIN_PASSWORD
docker compose up -d --build
# 前端 http://localhost:5173
# 后端 API http://localhost:8000/docs
```

### 方式二：本地开发

如果使用 Docker 数据库方案，先启动基础设施（PostgreSQL / Redis / MinIO）：

```bash
docker compose up -d postgres redis minio
```

后端：

```bash
cd backend
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp ../.env.example ../.env
alembic upgrade head
cd ..
./start_dev.sh

# 也可以直接启动；视频预览连接较多时建议设置热重载退出超时
# cd backend && python run_dev.py
```

`start_dev.sh` 会一起启动本地 FastAPI、Vite 前端和 Celery 队列，并复用已经运行的 Redis；按 `Ctrl+C` 会一起停止本地开发服务。停止但不删除数据可执行 `./stop_dev.sh`。

当前 `.env` 使用 SQLite + 本地素材存储时，不需要启动 PostgreSQL 或 MinIO；只需确保 Redis 已安装（脚本会在 macOS 上自动尝试启动 Homebrew Redis）。SQLite 数据和素材文件会原样保留。

前端：

```bash
cd frontend
npm install
npm run dev
```

> 无 Docker 环境时，将 `.env` 中的 `DATABASE_URL` 改为 `sqlite:///./app.db`、各 `AI_*_PROVIDER` 改为 `disabled`、`USE_CELERY=false` 即可在本地（含 Mock AI）完整运行。

### Mock 演示模式

未配置任何 AI API Key 时系统自动启用 Mock 模式：

```bash
# .env 示例
AI_LLM_PROVIDER=disabled          # 或 kimi / openai
AI_IMAGE_PROVIDER=disabled        # 或 minimax / openai
AI_VIDEO_PROVIDER=disabled
AI_TTS_PROVIDER=disabled
```

Mock 模式下所有 AI 功能返回可用的演示数据，页面全流程可操作。

### 认证与文件访问

浏览器登录态使用 `HttpOnly` Cookie（`fastvideo_access`），前端不会把 JWT 写入
`localStorage`，文件 URL 也不接受 `?token=`。Bearer Token 仅保留给脚本或服务端 API
客户端使用。生产环境必须设置 `APP_ENV=production`、`DEBUG=false`、长度至少 32 位的
随机 `SECRET_KEY`、强管理员密码，并启用 `AUTH_COOKIE_SECURE=true`（HTTPS）。
生产环境还应设置 `ALLOW_PUBLIC_REGISTRATION=false`；管理员在人员管理页创建账号。AI
Provider 密钥通过设置页保存时会以加密形式落库，Worker 会在任务开始前刷新配置。
加密密钥由 `SECRET_KEY` 派生；更换 `SECRET_KEY` 前请先迁移或重新录入已保存的 Provider Key，避免历史密钥无法解密。

## 🔌 AI 服务接入

所有 AI 服务统一走 `backend/app/adapters/` 下的适配器，新增服务只需实现统一接口并在 `config.py` 中选择 provider：

| 能力 | 适配器 | 支持 Provider |
|---|---|---|
| LLM 解说词生成 | `adapters/llm.py` | `kimi`（默认）/ `deepseek` / `openai` / `disabled`(mock) |
| 提示词大师（首尾帧视觉理解） | `adapters/llm.py` | `kimi`（默认，文本+图片输入）/ `disabled`(mock) |
| 图片生成/参考图渲染 | `adapters/image.py` | `seedream`（默认）/ `minimax` / `openai` / `disabled`(mock) |
| 图生视频/首尾帧视频 | `adapters/video.py` | `seedance`（默认）/ `minimax` / `disabled`(mock) |
| TTS 配音 | `adapters/tts.py` | `volcengine`（火山豆包语音）/ `openai` / `disabled`(mock) |

推荐的真实 Provider 组合已经接入：

```dotenv
# 根目录 .env（已被 .gitignore 忽略）
# 解说词、工程信息提取、提示词大师统一使用 Kimi
AI_LLM_PROVIDER=kimi
AI_LLM_MODEL=kimi-k3
AI_PROMPT_MASTER_PROVIDER=kimi
AI_PROMPT_MASTER_MODEL=kimi-k3
KIMI_API_KEY=在这里填写MoonshotKey

# 图生图默认 Seedream 4.5（火山方舟 Ark）
AI_IMAGE_PROVIDER=seedream
AI_IMAGE_MODEL=doubao-seedream-4-5-251128
SEEDREAM_API_KEY=在这里填写火山方舟APIKey   # 可复用 SEEDANCE_API_KEY

# 视频生成默认 Seedance 2.0 标准档（火山方舟 Ark）
AI_VIDEO_PROVIDER=seedance
AI_VIDEO_MODEL=doubao-seedance-2-0-260128
SEEDANCE_API_KEY=在这里填写火山方舟APIKey
SEEDANCE_BASE_URL=https://ark.cn-beijing.volces.com/api/v3
```

**API Key 填入位置**：解说词、工程信息提取和提示词大师统一使用 Kimi，填写 `.env` 的 `KIMI_API_KEY`；图生图（Seedream）与图生视频（Seedance）仍使用火山方舟 API Key，填写 `ARK_API_KEY` 或 `SEEDANCE_API_KEY`。MiniMax 仅当 `AI_IMAGE_PROVIDER=minimax` / `AI_VIDEO_PROVIDER=minimax` 时才需要 `MINIMAX_API_KEY`。

Seedream 4.5 图生图通过 `image` 参数传入参考图（base64 Data URL），`size` 支持 `2K/4K` 或像素值；模型名与基础地址可配置，默认 `doubao-seedream-4-5-251128`。Seedance 2.0 标准档模型 `doubao-seedance-2-0-260128` 支持首帧/首尾帧图生视频，默认关闭生成声音。Key 留空时相应模块自动降级 Mock。修改 `.env` 后须重启 API 和 Celery Worker。

国内 MiniMax 账号使用 `api.minimaxi.com`；海外账号把 `MINIMAX_BASE_URL` 改为 `https://api.minimax.io`。Seedance 的模型名与基础地址均可配置；Key 留空时相应模块自动降级 Mock。修改 `.env` 后须重启 API 和 Celery Worker。

Seedance 视频生成适配器能力矩阵：`image_to_video: true`、`first_last_frame_video: true`、`text_to_video: false`（本期不开放文生视频）、`async_task: true`、`cancel_task: true`。首尾帧模式必须显式传入两张图片（顺序固定先首帧后尾帧），不支持时禁用、不允许降级为普通图生视频。默认关闭生成声音，避免不可控音效/对白。

MiniMax 的公开图生图接口目前以 `subject_reference` 为主，并不是 BIM/建筑几何约束模型。平台会执行结构一致性辅助检查，但正式投标仍须人工核对楼层、轮廓、道路和设备位置；MiniMax 不支持的局部重绘、扩图和超分按钮会被能力矩阵禁用，不会静默降级。

当前真实配音使用**火山引擎豆包语音合成**（也可切换 OpenAI TTS）。若 `AI_TTS_PROVIDER=disabled`，可以完成演示版导出，但正式版预检会拒绝 Mock 配音；请配置已授权的真实音色或上传人工配音。

### 火山引擎豆包语音合成接入

在 `.env` 配置（`AI_TTS_PROVIDER=volcengine`）：

```dotenv
AI_TTS_PROVIDER=volcengine
VOLCENGINE_TTS_API_KEY=在这里填写语音合成APIKey
VOLCENGINE_TTS_BASE_URL=https://openspeech.bytedance.com/api/v3/tts/unidirectional/sse
VOLCENGINE_TTS_RESOURCE_ID=seed-tts-2.0
VOLCENGINE_TTS_VOICE=zh_female_xiaohe_uranus_bigtts
```

说明：
- 语音合成 API Key 在**火山引擎控制台 →「语音技术 → API Key 管理」**创建，与方舟 Ark 的 Key（Seedream/Seedance 用）不是同一个。
- 适配器 `VolcengineTTSAdapter` 走官方单向流式 SSE 接口 `POST /api/v3/tts/unidirectional/sse`，鉴权用 `X-Api-Key` + `X-Api-Resource-Id`。
- 内置 10 个豆包 2.0 音色（小何/云舟/灿灿/小天/高冷御姐/Tim/Dacey 等），启动时自动种子 5 个系统配音模板（`voice_provider=volcengine`），在「配音制作」页直接选用。
- 支持语速、音调、响度调节；豆包返回 mp3，平台自动转 wav（48kHz）用于波形/时长/字幕。

### 大文件招标资料上传

普通资料上限为 30MB；超过该大小的 PDF、DOCX、TXT 会自动改用 10MB 分片上传，支持 1GB 以内文件的断点续传。上传中断后重新选择同一文件，浏览器会从已完成分片继续；合并完成后自动进入原有的后台文档解析队列。请保留浏览器页面直到“上传成功，正在自动解析”提示出现。

## ✅ 测试与构建

```bash
# 后端
cd backend && pytest -q

# 前端
cd frontend && npm run build
```

### 当前验证结果
- 后端全量测试：**228 passed**；覆盖文档解析、渲染、配音、视频工程、AI 视频、上传安全、AI 配置刷新和认证限流。运行前仍应以当前分支实际 pytest 结果为准
- 前端 `tsc -b` + `vite build --outDir /tmp`：**构建成功**（存在主包体积优化提示，不影响运行）
- Alembic 迁移：`alembic upgrade head` 到 **0019 head**，包含视频生成、叙事证据、模板参考帧、分镜视觉绑定、项目级幂等约束和版本号唯一约束等表结构
- Seedance 契约验收：图生视频（1 张首帧）、首尾帧（2 张图顺序固定）、禁文生视频回退、异步轮询/下载/取消、模型与地址可配置均通过 Mock HTTP 测试；因未提供真实 Seedance Key，未执行付费线上调用
- 浏览器点击验收：登录 → 新建项目 → 项目详情 → 解说词与分镜 → 画面制作 → AI 视频生成 → 配音制作 → 视频工作区；控制台无 error/warn

### Mock 演示
- 演示账号：`admin@fastvideo.cn / admin123456`
- 演示资料：`sample_data/东部新城科创中心招标文件.txt`（虚构工程，不涉真实企业隐私）
- 渲染演示：`cd backend && python scripts/seed_render_demo.py <project_id>`（Pillow 生成 3 张模型截图 + 6 个 Mock 渲染版本 + 分镜绑定）
- Mock 操作路径：项目详情 → 画面制作 → 上传模型截图 → 选择 12 预设之一 → 设置参数 → 生成 → 对比/选择版本 → 设为分镜画面

## 📂 修改文件清单

**Phase 1（工程骨架）**：`.env.example / .gitignore / README.md / task_plan.md / docker-compose.yml`；`backend/`（Dockerfile / alembic / app.core / app.models / app.schemas / app.adapters / app.api.v1 / app.services.task_runner / app.tasks / tests）；`frontend/`（Dockerfile / nginx.conf / vite.config.ts / src 全部页面与组件）

**Phase 2（文档解析 + 解说词拆解）**：
```
新增：
├── backend/
│   ├── alembic/versions/0002_document_parsing_scoring.py   # 4 张新表 + 扩展字段
│   ├── app/adapters/ocr.py                                 # MockOCR + TesseractOCR
│   ├── app/models/ (document_page, document_chunk, extracted_fact, scoring_point)
│   ├── app/schemas/document.py                             # 阅读器/参数/评分点 Schema
│   ├── app/services/ (document_parser, fact_extractor, scoring_service, narration_engine)
│   ├── app/api/v1/ (reader.py, facts.py, scoring.py)       # 阅读器/参数台账/评分点路由
│   ├── tests/ (test_phase2_document_parsing.py, test_phase2_parser_unit.py)
│   └── requirements.txt (+ reportlab)
├── frontend/src/pages/ (DocumentReader.tsx, Facts.tsx)
└── sample_data/东部新城科创中心招标文件.txt                # 演示资料
修改：
├── backend/app/adapters/ (factory.py, llm.py)              # OCR 工厂 + Mock 解说词升级
├── backend/app/models/ (source_document, storyboard_shot, project, __init__)
├── backend/app/api/v1/ (documents.py 增强, storyboard.py 增强)
├── backend/app/tasks/ (document_parse.py, narration.py)
├── backend/app/main.py                                     # 挂载新路由
├── backend/app/schemas/ (source_document, storyboard_shot)
└── frontend/src/ (App.tsx, api/index.ts, api/types.ts, AppLayout.tsx, ProjectDetail.tsx, Storyboard.tsx)
```

**Phase 3（模型截图渲染 + 分镜绑定）**：
```
新增：
├── backend/
│   ├── alembic/versions/0003_render_tables.py              # render_presets/jobs/versions + 扩展 assets/storyboard_shots
│   ├── app/models/ (render_preset, render_job, render_version)
│   ├── app/schemas/render.py                               # 预设/任务/版本/遮罩/操作 Schema
│   ├── app/services/ (image_utils, prompt_builder, render_service)
│   ├── app/api/v1/ (render.py, render_presets.py)          # 渲染/预设路由
│   ├── app/tasks/render.py                                 # 渲染 Celery 任务
│   ├── scripts/seed_render_demo.py                         # 演示数据脚本
│   └── tests/test_phase3_render.py                         # 34 项测试
└── frontend/src/pages/RenderWorkspace.tsx                  # 画面制作三栏页面
修改：
├── backend/app/adapters/ (image.py 能力声明式重构, factory.py)
├── backend/app/models/ (asset 扩展, storyboard_shot 扩展, project, __init__)
├── backend/app/api/v1/storyboard.py                        # visual select/history/restore 端点
├── backend/app/schemas/storyboard_shot.py                  # render_version_id 等字段
├── backend/app/tasks/assets.py / celery_app.py
├── backend/app/main.py                                     # 挂载新路由
└── frontend/src/ (App.tsx, api/index.ts, api/types.ts, AppLayout.tsx, ProjectDetail.tsx)
```

**Phase 4（配音模板 + 时长适配 + 音频版本 + SRT 字幕）**：
```
新增：
├── backend/
│   ├── alembic/versions/0004_voice_pronunciation_audio.py   # voice_templates 扩展 + audio_versions/发音词典/audit_logs + render_tasks.parent_task_id
│   ├── app/models/ (audio_version, pronunciation, audit_log)
│   ├── app/schemas/voice.py                                 # 模板/发音/估算/生成/字幕/版本 Schema
│   ├── app/services/ (narration_normalizer, pronunciation_service, audio_utils, voice_service, audit)
│   ├── app/api/v1/voice.py                                  # 发音词典/配音/分镜配音 三路由器
│   ├── app/tasks/voice.py                                   # gen_voice_version Celery 任务 + 批量聚合
│   └── tests/test_phase4_voice.py                           # 29 项测试
└── frontend/src/
    ├── pages/VoiceWorkspace.tsx                             # 配音制作三栏工作区
    ├── pages/VoiceTemplates.tsx                             # 配音模板管理页
    └── components/PronunciationModal.tsx                    # 发音词典弹窗
修改：
├── backend/app/adapters/tts.py                              # 能力声明式重构 + Mock 真实 WAV 生成
├── backend/app/adapters/factory.py                          # tts_provider_info + capabilities
├── backend/app/models/ (voice_template 扩展, render_task.parent_task_id, storyboard_shot 解说词哈希)
├── backend/app/api/v1/ (voices.py 全局模板路由, storyboard.py 解说词变化追踪)
├── backend/app/services/render_service.py                   # 视频段重建原因参数化
├── backend/app/tasks/celery_app.py
├── backend/app/main.py                                      # 挂载新路由 + 发音词典种子
└── frontend/src/ (App.tsx, AppLayout.tsx, api/index.ts, api/types.ts)
```

**Phase 5（多分段视频合成 + 时间轴 + 正式导出）**：
```
新增：
├── backend/
│   ├── alembic/versions/0005_video_segments.py              # video_segments + video_projects/export_tasks 扩展
│   ├── app/models/video_segment.py                          # 视频分段模型
│   ├── app/schemas/video.py                                 # 分段/预检/导出 Schema 扩展
│   ├── app/services/video_composer.py                       # FFmpeg 合成引擎
│   ├── app/services/video_project_service.py                # 编排/缓存/预检/导出
│   ├── app/tasks/video_export.py                            # compose_project / render_segment 任务
│   └── tests/test_phase5_video.py                           # 21 项测试
└── frontend/src/pages/Video.tsx                             # 视频工作区（时间轴/预览/导出）
修改：
├── backend/app/models/ (video_project, export_task, __init__)
├── backend/app/api/v1/video.py                              # 分段/预检/导出端点
├── backend/app/tasks/celery_app.py
└── frontend/src/ (api/index.ts, api/types.ts)
```

**Phase 6/7（AI 视频生成 · Seedance 图片驱动视频素材）**：
```
新增：
├── backend/
│   ├── alembic/versions/0019_version_number_constraints.py  # 当前迁移链 head
│   ├── app/models/video_generation.py                        # 模板/任务/版本 数据实体
│   ├── app/schemas/video_gen.py                              # 模板/任务/版本/绑定/约束 Schema
│   ├── app/services/video_gen_templates.py                   # 42 个内置建筑视频模板 + 建筑强约束
│   ├── app/services/video_gen_service.py                     # 任务编排/约束拦截/版本管理
│   ├── app/tasks/video_gen.py                                # 视频生成 Celery 任务 + 同步降级
│   ├── app/api/v1/video_gen.py                               # /projects/{id}/ai-video 路由
│   └── tests/test_phase7_ai_video.py                         # 20 项测试
└── frontend/src/pages/AiVideo.tsx                            # AI 视频生成三栏页面
修改：
├── backend/app/adapters/video.py                             # + SeedanceVideoAdapter（保留 MiniMax）
├── backend/app/adapters/base.py                              # + supports() 能力查询
├── backend/app/adapters/factory.py                           # seedance provider + video_provider_info
├── backend/app/core/config.py                                # Seedance 配置项
├── backend/app/models/__init__.py
├── backend/app/main.py                                       # 挂载路由 + 模板种子
├── backend/app/tasks/celery_app.py                           # 注册 video_gen 任务
├── backend/tests/test_provider_integrations.py               # + Seedance 契约测试 8 项
├── .env / .env.example                                       # Seedance 配置
├── docker-compose.yml                                        # Seedance 环境变量
└── frontend/src/ (App.tsx 路由, AppLayout.tsx 菜单, api/index.ts, api/types.ts)
```

## 📄 文档

- [开发计划](task_plan.md)
---

> ⚠️ 提示：请勿将 `.env` / 任何 API Key 提交到代码仓库。
