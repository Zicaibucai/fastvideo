# 建筑工程AI投标视频平台 — 开发计划

## 目标
构建一个全栈、可运行的"建筑工程AI投标视频平台"：用户上传招标文件/施工组织设计/模型截图/素材，系统自动完成解说词拆解、画面生成、AI配音、多分段视频合成和素材复用，导出 16:9 1080P 投标视频。

## 技术栈
- 前端: React + TypeScript + Vite + Ant Design
- 后端: Python FastAPI
- 数据库: PostgreSQL (SQLAlchemy + Alembic)
- 任务队列: Redis + Celery
- 文件存储: 本地存储 + MinIO 兼容
- 视频处理: FFmpeg
- 部署: Docker Compose
- AI服务: Adapter 适配器模式（DeepSeek V4 Flash 文本 / MiniMax 图片与 Hailuo 视频 / OpenAI TTS）+ Mock 降级

## 核心数据实体
User / Project / SourceDocument / StoryboardShot / Asset / RenderTask / VoiceTemplate / VideoProject / ExportTask

## 阶段
### Phase 1: 工程骨架 (本次) ✅ 已完成
- [x] 检查现有项目（空项目）
- [x] 创建仓库结构、目录树
- [x] 后端 FastAPI 骨架：config、异常处理、日志、DB连接、健康检查
- [x] SQLAlchemy 模型 + Alembic 迁移
- [x] AI Adapter 层（LLM/Image/Video/TTS + Mock）
- [x] Celery + Redis 任务队列，异步任务示例
- [x] 前端 React+TS+Vite+AntD 骨架
- [x] Docker Compose (postgres/redis/minio/api/worker/frontend)
- [x] README、.env.example、测试、构建验证

**Phase 1 测试结果：**
- 后端 pytest：9 passed（健康检查/认证/项目CRUD/AI解说词/版本历史/Mock图片/导出）
- 前端 `npm run build`：构建成功
- E2E 全流程验证：登录→建项目→AI生成解说词→编辑分镜→生成画面→生成配音→创建视频工程→导出 MP4
- 导出视频 ffprobe 验证：1920×1080 / 30fps / H.264 / 8s ✅

**Phase 1 修复记录：**
- FastAPI 204 路由 `-> None` 注解在 `from __future__ import annotations` 下会误判响应模型 → 移除注解
- passlib 1.7.4 与 bcrypt 4.x 不兼容 → 改用标准库 PBKDF2 实现密码哈希
- email-validator 拒绝 `.local` 保留域名 → 默认管理员邮箱改为 `admin@fastvideo.cn`
- SQLAlchemy JSON 列原地修改不触发变更检测 → 历史版本用新列表对象赋值
- 存储路径 `BASE_DIR` 计算错误 → 修正为 backend 根目录

### Phase 2: 工程文档精准解析 + 解说词智能拆解 ✅ 已完成
- [x] 新增 DocumentPage / DocumentChunk / ExtractedFact / ScoringPoint 模型（Alembic 0002 迁移）
- [x] 按页解析 PDF（pdfplumber）/ DOCX / TXT，提取表格与目录结构
- [x] 扫描页检测 + OCR（MockOCRAdapter + TesseractOCRAdapter，不可用降级不失败）
- [x] 20 类工程参数提取（面积/工期/日期/高度/层数/金额/评分项等，含来源页码与置信度）
- [x] 参数冲突检测（conflict 标记，不自动选择），人工确认/驳回/修改
- [x] 评分点提取（含分类与分值）与分镜覆盖率统计
- [x] 解说词智能拆解引擎（Pydantic 严格校验，10+ 分镜，含来源引用/factCheckStatus）
- [x] 前端文档阅读器（三栏）/ 工程参数台账 / 分镜编辑器增强（生成配置/排序/版本/来源跳转）
- [x] 演示资料 sample_data/东部新城科创中心招标文件.txt
- [x] 新增测试 test_phase2_*（PDF/DOCX解析/OCR降级/重复检测/参数页码/冲突/无来源拦截/JSON异常/Mock分镜/排序持久化/权限隔离）

**Phase 2 测试结果：**
- 后端 pytest：**31 passed**（Phase 1 的 9 个 + Phase 2 的 22 个）
- 前端 `tsc -b` + `vite build`：构建成功
- E2E 演示流程：登录→建项目→上传演示TXT→按页解析→提取17个参数→确认→生成10分镜→编辑→拖拽排序刷新持久→单分镜重生成→评分点覆盖率→文档搜索→阅读器
- Alembic 迁移 0002：成功创建 4 张新表 + 扩展 source_documents/storyboard_shots

**Phase 2 修复记录：**
- 0002 迁移在 `create_all` 之上重复 add_column → 增加 `_add_column_if_missing` 守卫
- 冲突检测只检查单文档 → 改为对项目全部事实重新检测
- Mock 分镜 sourceReferences 用占位 documentId → 映射到项目实际文档

### Phase 3: 模型截图智能渲染与分镜画面绑定 ✅ 已完成
- [x] 新增 RenderPreset / RenderJob / RenderVersion 模型（Alembic 0003 迁移，共 17 张表）
- [x] 12 种系统渲染预设（工业厂房/施工现场/科技蓝/日景夜景/总平鸟瞰/白模/BIM/绿色/安全/机电/钢结构）
- [x] 图片上传校验（30MB/最小尺寸/EXIF方向/去除EXIF/SHA-256去重/缩略图/禁止SVG/解压炸弹防护）
- [x] PromptBuilder 服务（系统级结构保持提示不可删，冲突结构修改请求拦截）
- [x] ImageAdapter 能力声明式重构（capabilities：img2img/inpaint/outpaint/upscale/seed 等）
- [x] Mock 渲染用 Pillow 生成真实 PNG（色彩分级/滤镜/局部重绘/扩图/清晰度增强/确定性seed）
- [x] 结构一致性辅助检查（SSIM/边缘重合/变化比例/全黑全白，标"辅助检查"）
- [x] 版本管理（原图V0、生成V1起、软删除、引用检查、历史恢复）
- [x] 分镜画面绑定（来源链：分镜→结果→版本→源图；视频段需重建标记）
- [x] 成本控制与任务控制（预估/实际成本、幂等键、重试/取消）
- [x] 前端 RenderWorkspace 页面（三栏：分镜列表/预览对比/参数表单+遮罩）
- [x] 演示数据脚本 scripts/seed_render_demo.py（3 源图 + 6 Mock 版本 + 绑定）
- [x] 新增测试 test_phase3_render.py（34 项）

**Phase 3 测试结果：**
- 后端 pytest：**65 passed**（Phase1 9 + Phase2 22 + Phase3 34）
- 前端 `tsc -b` + `vite build`：构建成功
- Alembic 迁移 0003：成功创建 17 张表
- E2E 演示流程：建项目→5分镜→种子3源图→6 Mock渲染→V0版本→分镜绑定→刷新持久→视频段标记
- Mock 渲染实际生成真实 PNG 文件（非 URL 占位），质量检查通过

**Phase 3 修复记录：**
- Project.render_presets 关系无 FK → 移除（预设为全局表）
- InpaintRequest 未导入导致 FastAPI 当 Query → 补导入
- EXIF 转置前校验尺寸 → 先转置再校验
- 新字段未加入 StoryboardShotOut schema → 补充 render_version_id 等

### Phase 4: AI 配音模板、时长智能适配、音频版本管理与 SRT 字幕生成 ✅ 已完成
- [x] 扩展 VoiceTemplate：描述/音色/风格/模型/音量/停顿强度/情绪/授权（type+status+note+expire）/启用状态，8 种说话风格预设
- [x] 新增 AudioVersion（配音版本表）、PronunciationProfile/Rule（发音词典）、AuditLog（审计日志），Alembic 0004 迁移（21 张表）
- [x] render_tasks.parent_task_id（批量父任务）、storyboard_shots 解说词哈希追踪（narration_hash/prev_hash/updated_at）
- [x] TTSAdapter 能力声明式重构：synthesize/list_voices/preview_voice/get_capabilities/get_task_status/cancel_task/normalize_error；不支持参数明确 CapabilityError
- [x] Mock TTS：生成真实 WAV（PCM 16-bit/48kHz/单声道），确定性 seed，提示音模拟句子，WAV↔MP3 转换，标记 Mock Audio
- [x] NarrationNormalizer 中文朗读规范化：日期/时间/百分数/金额/工期/㎡/m³/米/毫米/千牛/兆帕/摄氏度/楼层/标段/序号/缩写/BIM/EPC/PC/MEP/C40 混凝土等，不修改原解说词
- [x] 发音词典服务：系统/企业/项目三级，项目优先级最高，导入导出 JSON、朗读测试、ReDoS 正则防护
- [x] 时长估算（中文/英文/数字展开/标点停顿/语速/停顿强度）+ 生成后真实时长读取（ffprobe）+ 适配规则（≤5% matched / 5~12% 微调 / >12% script_adjustment_required）
- [x] 音频质量检查（可解码/格式/采样率/声道/时长/静音占比/峰值/削波/简化响度）+ 波形数据（固定采样点）
- [x] 字幕生成（按标点切句+权重分配，不拆日期数字单位，支持人工修改与防重叠）+ 单条/项目级 UTF-8 SRT 导出
- [x] 配音版本管理：V1 起递增、不覆盖、软删除+引用检查、设为正式/恢复历史、Mock 标记
- [x] 解说词变化追踪：修改后旧配音与字幕标记 stale，保存前后哈希，可检测可复用历史音频
- [x] 批量生成（父任务 tts_batch + 子任务 gen_voice_version）、幂等键、失败单条重试、取消
- [x] 导出：全部 WAV/MP3（zip）、项目 SRT、单条分镜 SRT；正式导出校验音色授权
- [x] 前端：配音制作三栏工作区（分镜列表/朗读与版本/模板参数）、配音模板管理页、发音词典/字幕编辑/批量生成弹窗、波形、试听、批量任务进度
- [x] 审计日志（模板创建/修改/试听、单条配音、批量生成、版本选择等）
- [x] 新增测试 test_phase4_voice.py（29 项）

**Phase 4 测试结果：**
- 后端 pytest：**94 passed**（Phase1 9 + Phase2 22 + Phase3 34 + Phase4 29）
- 前端 `tsc -b` + `vite build`：构建成功
- Alembic 迁移 0004：成功创建 21 张表
- E2E 演示流程：建项目→分镜→发音词典（EPC→E P C）→估算→单条生成→批量生成→V1/V2 版本→选择/删除/恢复→解说词修改标 stale→字幕编辑→导出 SRT→汇总

**Phase 4 修复记录：**
- MockTTSAdapter MRO 导致 provider 解析为 openai → 显式设置 provider="mock"
- 切句正则把小数点 "8.5" 切开 → 仅非数字夹持的 '.' 切分
- 中文数字 10-19 误读"一十X" → 修正为"十X"
- 危险正则检测漏掉 `(a+)+` → 增加分组外再量词模式
- 字幕编辑校验需防止重叠/超时长 → 全量有序校验

### Phase 5: 多分段视频合成、可视化时间轴与正式成片导出 ✅ 已完成
- [x] 新增 VideoSegment 模型（画面/配音/时长/运动/适配/转场/字幕/音量/渲染状态/input_hash），Alembic 0005 迁移（22 张表）
- [x] VideoProject 扩展：字幕样式/音乐轨/Logo/片头片尾/品牌色/导出模式/时间轴快照；ExportTask 扩展 mode/srt_key/report_key/timeline_snapshot
- [x] FFmpeg 合成引擎 `services/video_composer.py`：图片→动态分段（Ken Burns 6 种运动 + cover/contain/fill/blur）、视频素材标准化（循环/裁切/变速）、ASS 字幕生成与烧录、xfade 转场拼接、acrossfade 音频拼接、背景音乐（循环/淡入淡出）+ sidechaincompress ducking、Logo 叠加、片头片尾标题卡、音视频 mux
- [x] 全链路编排 `services/video_project_service.py`：sync-storyboard、素材选择优先级（手动>绑定视频>AI图>模型截图>占位卡）、时长=配音实际+片头尾停顿、input_hash 缓存、preflight（demo/formal 严格区分：Mock/占位/未授权音色/未确认工程事实/缺失画面）、单分镜渲染、全片合成、项目级 SRT（含转场重叠）、导出报告
- [x] 异步任务：单分镜渲染/批量渲染（父任务+子任务+进度聚合）/全片合成/导出 demo/formal/失败重试/取消；幂等与缓存（成功分段不重复渲染）
- [x] API：sync-storyboard、segments CRUD/reorder、preview/render/retry、render-all、preflight、export/demo、export/formal、exports、download/srt/report
- [x] 前端 Video 工作区：分镜列表+排序、视频预览、多轨时间轴、分段参数面板、预检面板、导出记录与下载；保留旧导出端点兼容
- [x] 新增测试 test_phase5_video.py（21 项：标准分段/不拉伸/冻结尾帧/静音轨/字幕烧录/UTF-8 SRT/中文字体/音乐 ducking/转场时长/Logo/片头片尾/input_hash 缓存/变化触发重建/失败重试/批量部分失败/正式导出拒绝 Mock/缺失画面/未确认事实/权限隔离/命令注入防护）

**Phase 5 测试结果：**
- 后端 pytest：**115 passed**（Phase1 9 + Phase2 22 + Phase3 34 + Phase4 29 + Phase5 21）
- 前端 `tsc -b` + `vite build`：构建成功
- Alembic 迁移 0005：成功创建 22 张表
- E2E：分镜→配音→画面→分段渲染→演示导出→下载 MP4/SRT/报告；ffprobe 验证最终 1920×1080 / 25fps / H.264 / yuv420p / AAC 48k 立体声
- 正式导出 preflight 正确拒绝 Mock 音频 / 未授权音色 / 缺失画面 / 未确认工程事实

**Phase 5 修复记录：**
- xfade 拼接 `prev_label` 未更新导致第二段引用错误 → 循环内更新 prev_label
- xfade offset 公式错误 → 改为 `sum(durations) - sum(transitions)` 累计
- sidechaincompress 第二输入不能用过滤器标签（ffmpeg 4.4 兼容）→ 直接引用输入流
- asplit 多余输出未连接 → 简化 duck 图
- 项目级 SRT 累计公式错误 → 改为 `start_{i+1} = start_i + D_i - T_i`
- rollup arm64 可选依赖缺失（沙箱 npm bug）→ 手动安装 @rollup/rollup-linux-arm64-gnu

### Phase 6+: 由下一段功能提示词决定

### Phase 6/7: AI 视频生成模块（Seedance 图片驱动视频素材）✅ 已完成
- [x] 新增 `SeedanceVideoAdapter`（火山方舟 Ark），保留旧 MiniMax 代码但不再作为默认视频 Provider
- [x] Seedance 能力矩阵：image_to_video / first_last_frame_video / async_task / cancel_task / text_to_video=false
- [x] 图生视频上传 1 张首帧；首尾帧上传 2 张图片顺序固定 `[first_frame, last_frame]`；不支持时禁用，不允许降级
- [x] 默认关闭生成声音（generate_audio=false），避免不可控音效/对白
- [x] 异步提交 → 轮询 → 下载 MP4 → 记录原始任务 ID 与错误；支持时长/比例/分辨率/随机种子
- [x] 模型名、基础地址全可配置（AI_VIDEO_PROVIDER=seedance + SEEDANCE_* 环境变量）
- [x] 先为 Seedance API 编写 Mock HTTP 契约测试（8 项），再接真实调用
- [x] 新增数据实体 VideoGenerationTemplate / VideoGenerationJob / VideoGenerationVersion（Alembic 0007，3 张表）
- [x] 任务含完整参数快照、建筑约束快照、模型/Provider/时长/比例/分辨率/种子/声音、Seedance 任务 ID、结果素材 ID
- [x] 10 个首批内置建筑视频模板（含"建筑模型 → 施工现场过渡"指定默认提示词）
- [x] 建筑强约束默认启用并保存快照；冲突指令（增加楼层/改变建筑轮廓/移动道路/替换主楼）阻止提交
- [x] 独立页面 `/projects/:projectId/ai-video`（三栏：素材与参考帧 / 模板与提示词 / 参数与结果）
- [x] 视频提示词独立填写，不使用 narration/visual_prompt/image_prompt，无任何自动回退
- [x] 结果版本：预览/下载/选为当前结果/删除；AI 视频素材不绑定分镜，仅由视频工程分段选择；修改解说词不影响已配置视频任务
- [x] 接口：模板列表/管理、创建/查询/取消/重试任务、版本列表/选择/绑定/删除、约束预检、参考帧列表、Provider 能力
- [x] 新增测试 test_phase7_ai_video.py（20 项）；后端 pytest **149 passed**（另 2 项沙箱文件删除权限受限属环境限制）
- [x] 前端 tsc + vite build 通过；`.env` / `.env.example` / docker-compose 同步 Seedance 配置

### Provider 接入与验收补充（2026-08-14）✅
- [x] DeepSeek OpenAI 兼容 Chat Completions 接入，默认模型 `deepseek-v4-flash`
- [x] 解说词强制 JSON 输出、8000 token 上限，避免 10+ 分镜被截断
- [x] MiniMax `image-01` 文生图与 subject reference 参考图渲染接入
- [x] MiniMax Hailuo 创建任务→轮询→文件查询→MP4 下载完整链路
- [x] 分镜已选画面自动作为 MiniMax 图生视频首帧；无画面时切换文本视频模型
- [x] Provider 能力矩阵诚实禁用 MiniMax 未支持的 inpaint/outpaint/upscale
- [x] 真实 Provider/Mock 素材来源正确落库，正式导出拒绝 Mock 画面与旧版 Mock 配音
- [x] `.env` / Docker Compose 分离传入 `DEEPSEEK_API_KEY` 与 `MINIMAX_API_KEY`
- [x] Docker 镜像补齐 Noto CJK、libass、drawtext；全量 **120 passed**
- [x] 前端构建通过，浏览器登录/建项目/四个核心制作工作区点击通过，控制台无告警

## 关键设计决策
- 所有 AI 接口经 Adapter 层，未配置 API Key 时自动进入 Mock 演示模式，保证全部页面与流程可运行。
- API Key 一律走 .env，不进代码。
- 耗时 AI 任务走 Celery 异步队列，前端展示 排队/处理中/成功/失败/重试 状态。
- AI 结果支持人工编辑、重新生成、历史版本恢复。
- 招标文件关键参数（面积、日期、工期、技术参数）必须记录来源页码，防止 AI 编造。

## 运行方式（开发）
```bash
# 后端
cd backend && python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000

# 前端
cd frontend && npm install && npm run dev

# 基础设施（可选，本地无 Docker 时后端可用 SQLite + 内存队列降级）
docker compose up -d postgres redis minio
```
