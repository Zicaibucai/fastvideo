# Phase 6/7 交付说明：AI 视频生成模块（Seedance 图片驱动视频分镜）

> 交付日期：2026-08-14 ｜ 目标：将现有 MiniMax 视频生成替换为 Seedance，建立「图片驱动视频分镜」工作流。
> 独立于「解说词与分镜」页面；不使用 `narration` / `visual_prompt` / `image_prompt`；无任何自动回退。

---

## 一、改动文件清单

### 后端（新增）
```
backend/
├── alembic/versions/0007_ai_video_generation.py     # video_generation_templates / jobs / versions 三张表
├── app/models/video_generation.py                    # 模板 / 任务 / 版本 数据实体
├── app/schemas/video_gen.py                          # 模板 / 任务 / 版本 / 绑定 / 约束 / 参考帧 Schema
├── app/services/video_gen_templates.py               # 10 个内置建筑视频模板 + 建筑强约束常量
├── app/services/video_gen_service.py                 # 任务编排 / 约束拦截 / 版本管理 / 绑定分镜
├── app/tasks/video_gen.py                            # 视频生成 Celery 任务 + 同步降级
├── app/api/v1/video_gen.py                           # /projects/{project_id}/ai-video 路由
└── tests/test_phase7_ai_video.py                     # 20 项测试
```

### 后端（修改）
```
backend/
├── app/adapters/video.py                             # 新增 SeedanceVideoAdapter（保留 MiniMax 代码）
├── app/adapters/image.py                             # 新增 SeedreamImageAdapter（Seedream 4.5 图生图，保留 MiniMax 代码）
├── app/adapters/base.py                              # BaseAIAdapter 新增 supports() 能力查询
├── app/adapters/factory.py                           # seedance / seedream provider 分支 + video_provider_info()
├── app/core/config.py                                # Seedance / Seedream 配置项 + ai_keys_configured
├── app/models/__init__.py                            # 注册三个新模型
├── app/main.py                                       # 挂载 video_gen 路由 + 模板种子
├── app/tasks/celery_app.py                           # 注册 fastvideo.video_gen_job 任务
└── tests/test_provider_integrations.py               # + Seedance 契约测试 8 项 + Seedream 契约测试 4 项
```

### 前端
```
frontend/src/
├── pages/AiVideo.tsx                                 # 新增：AI 视频生成三栏页面
├── App.tsx                                           # 路由 /project/:projectId/ai-video
├── components/AppLayout.tsx                          # 菜单项「AI 视频生成」
├── api/index.ts                                      # videoGenApi + downloadAiVideo()
└── api/types.ts                                      # VideoGenerationTemplate/Job/Version、ReferenceImage
```

### 配置 / 部署 / 文档
```
.env.example / .env           # Seedance 环境变量
docker-compose.yml            # api / worker 两块 Seedance 环境变量
README.md                     # 功能、接入、验证结果、文件清单
task_plan.md                  # Phase 6/7 完成记录
```

---

## 二、Seedance / Seedream 配置说明

`.env` 新增（模型名、基础地址必须可配置，禁止写死第三方网关地址或模型 ID）：

```dotenv
AI_VIDEO_PROVIDER=seedance                      # 默认视频 Provider
AI_VIDEO_MODEL=doubao-seedance-2-0-260128       # Seedance 2.0 标准档

AI_IMAGE_PROVIDER=seedream                      # 默认图生图 Provider
AI_IMAGE_MODEL=doubao-seedream-4-5-251128       # Seedream 4.5

SEEDANCE_API_KEY=                               # 火山方舟 Ark API Key（视频+图片共用）
SEEDANCE_BASE_URL=https://ark.cn-beijing.volces.com/api/v3
SEEDANCE_VIDEO_MODEL=doubao-seedance-2-0-260128
SEEDANCE_TIMEOUT=180                            # 单次 HTTP 超时（秒）
SEEDANCE_POLL_INTERVAL=10                       # 任务轮询间隔（秒）
SEEDANCE_VIDEO_TIMEOUT=900                      # 生成等待上限（秒）
SEEDANCE_VIDEO_RESOLUTION=720p                  # 默认分辨率 480p/720p/1080p

SEEDREAM_API_KEY=                               # 图生图 Key，可复用 SEEDANCE_API_KEY
SEEDREAM_BASE_URL=https://ark.cn-beijing.volces.com/api/v3
SEEDREAM_IMAGE_MODEL=doubao-seedream-4-5-251128
SEEDREAM_TIMEOUT=180
SEEDREAM_IMAGE_SIZE=2K                          # Seedream 4.5：2K / 4K / 像素值
```

**API Key 填入位置**：图生图（Seedream）与图生视频（Seedance）同属火山方舟，只需把**同一个火山方舟 API Key** 填入 `.env` 的 `SEEDANCE_API_KEY`（或单独 `SEEDREAM_API_KEY`）。Key 在[火山引擎控制台](https://console.volcengine.com/)「方舟 ARK → API Key 管理」创建。

说明：
- `AI_VIDEO_PROVIDER=seedance` 且配置了 `SEEDANCE_API_KEY` 时使用真实 Seedance；`AI_IMAGE_PROVIDER=seedream` 且配置了 `SEEDANCE_API_KEY` 或 `SEEDREAM_API_KEY` 时使用真实 Seedream；Key 留空自动回退 Mock 演示模式。
- Seedance 能力矩阵：`image_to_video: true`、`first_last_frame_video: true`、`text_to_video: false`（本期页面不开放文生视频）、`async_task: true`、`cancel_task: true`。
- Seedream 图生图通过 `image` 参数传参考图（base64 Data URL），模型默认 `doubao-seedream-4-5-251128`，`size` 支持 `2K/4K` 或像素值。
- 修改 `.env` 后需重启 API 与 Celery Worker。

---

## 三、接口说明

基础前缀：`/api/v1/projects/{project_id}/ai-video`

### 模板
| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/templates?mode=image_to_video` | 视频模板列表（可过滤模式） |
| GET | `/templates/{id}` | 模板详情 |
| POST | `/templates` | 创建企业模板 |
| PATCH | `/templates/{id}` | 更新模板（系统模板仅管理员） |
| DELETE | `/templates/{id}` | 删除模板（系统模板不可删，可停用） |

### Provider / 素材 / 约束
| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/providers` | 视频 Provider 列表（provider/available/capabilities/model/is_mock） |
| GET | `/providers/{provider}/capabilities` | Provider 能力矩阵 |
| GET | `/reference-images` | 可作首/尾帧的图片素材（系统不自动挑选） |
| POST | `/constraint-check` | 建筑约束冲突预检 `{text}` → `{conflicts, blocked}` |

### 任务
| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/tasks` | 创建视频生成任务（202）。`generation_mode` = `image_to_video`（仅首帧）或 `first_last_frame_video`（首帧+尾帧）；`positive_prompt` 为独立视频提示词；`constraints_enabled` 默认 true；`generate_audio` 默认 false |
| GET | `/tasks?status=&shot_id=` | 任务列表 |
| GET | `/tasks/{job_id}` | 任务详情（轮询） |
| POST | `/tasks/{job_id}/retry` | 重试失败任务 |
| POST | `/tasks/{job_id}/cancel` | 取消任务（并调用 Seedance DELETE） |
| GET | `/tasks/{job_id}/versions` | 任务结果版本列表 |

### 版本
| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/versions?shot_id=` | 项目视频版本列表 |
| POST | `/versions/{version_id}/select` | 选为当前结果 |
| POST | `/versions/{version_id}/bind` | 绑定到分镜 `{shot_id}` |
| DELETE | `/versions/{version_id}` | 软删除（已绑定分镜的版本拒绝删除） |

### 任务创建请求体
```json
{
  "storyboard_shot_id": null,
  "generation_mode": "image_to_video",        // 或 first_last_frame_video
  "first_frame_asset_id": "<图片素材ID>",      // 必填
  "last_frame_asset_id": "<图片素材ID>",       // 首尾帧模式必填
  "template_id": null,
  "positive_prompt": "独立视频提示词，不引用解说词",
  "negative_prompt": "",
  "duration": 5,
  "aspect_ratio": "adaptive",
  "resolution": "720p",
  "seed": null,
  "generate_audio": false,
  "constraints_enabled": true,
  "idempotency_key": null
}
```

### 任务对象关键字段
`VideoGenerationJob` 包含：项目 ID、可选分镜 ID、生成模式、首帧/尾帧素材 ID、模板 ID、正/负向提示词、建筑约束快照、Provider/模型、时长/比例/分辨率/随机种子/声音开关、Seedance 任务 ID、状态/进度/错误/耗时、结果素材 ID、创建人/创建时间、完整 `parameter_snapshot`（可复现）。

---

## 四、模板清单（10 个内置建筑视频模板）

| # | 模板名称 | 适用模式 | 推荐时长 | 推荐比例 | 镜头运动 |
|---|---|---|---|---|---|
| 1 | 建筑缓慢推进 | 图生视频 | 5s | 16:9 | 缓慢推进（dolly in） |
| 2 | 建筑环绕展示 | 图生视频 | 10s | 16:9 | 环绕（orbit） |
| 3 | 鸟瞰俯冲揭示 | 图生视频 | 5s | 16:9 | 俯冲（dive） |
| 4 | 人视走近主入口 | 图生视频 | 5s | 16:9 | 前移（dolly in） |
| 5 | 室内空间慢游 | 图生视频 | 5s | 16:9 | 平移（truck/pan） |
| 6 | 光影与树影微动 | 图生视频 | 5s | 16:9 | 固定/微动（static） |
| 7 | 白模/模型 → 写实效果图过渡 | 首尾帧 | 10s | adaptive | 缓慢推进 |
| 8 | 建筑模型 → 施工现场过渡 | 首尾帧 | 10s | adaptive | 缓慢推进 |
| 9 | 施工现场动态展示 | 图生视频 | 5s | 16:9 | 固定/慢摇 |
| 10 | 日景 → 夜景灯光过渡 | 首尾帧 | 10s | adaptive | 固定（static） |

其中模板 8「建筑模型 → 施工现场过渡」默认提示词严格按需求编写：
> 严格保持首帧中建筑的主体数量、体量、轮廓、层数、道路、主入口和主要构件关系不变。镜头以稳定的鸟瞰视角缓慢推进，建筑从干净的设计模型状态逐步转化为真实施工现场，出现合理的钢筋、模板、脚手架、塔吊和施工机械。最终画面准确过渡至尾帧所示施工阶段。镜头平稳，施工过程自然，写实工程纪录片质感。

每个模板还带默认负向提示词与默认建筑约束；点击模板卡片自动填入默认提示词与推荐参数，用户可编辑。

---

## 五、建筑强约束（默认启用并保存到任务快照）

锁定建筑主体数量、体量、轮廓、层数；锁定道路、主入口、主要门窗、设备位置；锁定建筑风格与主材质关系；保持首尾帧构图和空间关系；禁止新增/删除建筑主体、楼层、道路或主要设备；禁止建筑扭曲、立面漂移、严重透视错误；禁止乱码文字、虚假项目标识、重复车辆/人物；禁止不合理施工机械、悬浮构件、物理错误；禁止镜头快速乱飘、频繁切镜、无关主体出现。

冲突拦截：用户输入包含「增加楼层 / 删除楼层 / 改变建筑轮廓 / 移动道路 / 移动主入口 / 替换主楼 / 拆除重做」等指令时阻止提交并说明冲突原因（后端 409 + 前端预检双重拦截）。

---

## 六、测试结果

### 后端 pytest
- `tests/test_provider_integrations.py`：**24 passed**（原 6 项 + Seedance 契约 8 项 + Seedream 契约 4 项 + 火山豆包 TTS 契约 6 项）
- `tests/test_phase7_ai_video.py`：**20 passed**（模板种子 / 未选首帧拦截 / 首尾帧双图校验 / 约束冲突拦截×6 / 约束预检 / 禁解说词回退 / 修改解说词不影响任务 / 模板参数填充 / 任务查询选择绑定删除 / 参考帧列表 / 取消与幂等 / 企业模板 CRUD）
- 全量：**151 passed**；沙箱内 `test_phase5_video` 与 `test_phase6_resumable_upload` 共 2 项因「沙箱 backend 目录文件删除权限受限」无法通过，属既有环境限制，与本次改动无关（本机/容器环境可正常通过）。

### 前端
- `tsc -b`：**通过**
- `vite build --outDir /tmp/fv_dist`：**构建成功**（主包体积提示为非阻断）

### 验收核对
- [x] 修改分镜解说词后，不影响已配置的视频任务（测试验证）
- [x] 未选首帧时，不能提交图生视频（409 + 前端校验）
- [x] 首尾帧模式必须传入两张参考图并保留顺序（契约测试断言 `[first_frame, last_frame]`）
- [x] 每个生成视频可追溯到具体图片、模板、提示词和参数（`parameter_snapshot`）
- [x] 默认 Seedance Provider 生效，MiniMax 不再被默认调用（`.env` / 工厂分支 / 契约测试）
- [x] 前端构建通过；Seedance 图生视频、首尾帧、禁解说词回退、模板参数填充、约束拦截测试全部通过

### 未验证项
- 真实 Seedance 付费线上调用（沙箱无真实 Key）——适配器已按火山方舟 Ark 公开契约实现并通过 Mock HTTP 契约测试，接入真实 Key 后即可使用；如契约与线上有差异，只需调整 `SeedanceVideoAdapter` 的请求/解析字段。
- 真实火山豆包语音合成线上调用（`.env` 中 `VOLCENGINE_TTS_API_KEY` 未配置）——适配器已按官方单向流式 SSE 协议实现并通过 Mock HTTP 契约测试；填入语音合成 API Key 后即可使用。

---

## 七、火山引擎豆包语音合成接入（新增）

**配置**（`.env`，`AI_TTS_PROVIDER=volcengine`）：

```dotenv
AI_TTS_PROVIDER=volcengine
VOLCENGINE_TTS_API_KEY=             # 火山引擎「语音技术 → API Key 管理」创建（与方舟 Ark Key 不同）
VOLCENGINE_TTS_BASE_URL=https://openspeech.bytedance.com/api/v3/tts/unidirectional/sse
VOLCENGINE_TTS_RESOURCE_ID=seed-tts-2.0
VOLCENGINE_TTS_VOICE=zh_female_xiaohe_uranus_bigtts
VOLCENGINE_TTS_TIMEOUT=120
```

**适配器**：`backend/app/adapters/tts.py` 新增 `VolcengineTTSAdapter`（provider=`volcengine`）。

- 协议：`POST {base}/api/v3/tts/unidirectional/sse` 单向流式 SSE；请求头 `X-Api-Key` + `X-Api-Resource-Id`；返回 base64 音频分片，逐条 `data:` 事件解析。
- 能力：`synthesize / speed_control / pitch_control / volume_control / voice_preview / mp3 / wav`（豆包原生 mp3/pcm/ogg_opus，wav 由平台 `any_audio_to_wav` 转换）。
- 内置 10 个豆包 2.0 音色（`VOLCENGINE_VOICES`）：小何/云舟/灿灿/小天/高冷御姐/温柔淑女/心灵鸡汤/Tim/Dacey/Vivi。
- 启动时幂等种子 5 个系统配音模板（`voice_provider=volcengine`，如「豆包·小何」「豆包·云舟」），在「配音制作」页直接选用并试听。
- 语速映射：项目 `speed` 1.0=正常 → 豆包 `speech_rate` 0；1.5x→50，0.5x→-50。音调 `pitch`、响度 `volume` 通过 `post_process` 传给豆包。
- 文本上限 5000 字；不支持 `emotion`（2.0 音色无 emotion 参数，能力矩阵如实标注）。

**改动文件**：`backend/app/adapters/tts.py`、`backend/app/adapters/factory.py`、`backend/app/core/config.py`、`backend/app/api/v1/voices.py`、`backend/app/main.py`、`backend/tests/test_provider_integrations.py`、`.env` / `.env.example` / `docker-compose.yml`、`README.md`。
