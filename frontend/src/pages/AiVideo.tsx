import { useEffect, useMemo, useState } from 'react'
import type { CSSProperties } from 'react'
import {
  App,
  Alert,
  Button,
  Card,
  Col,
  Collapse,
  Divider,
  Drawer,
  Empty,
  FloatButton,
  Input,
  InputNumber,
  List,
  Modal,
  Progress,
  Row,
  Segmented,
  Select,
  Space,
  Switch,
  Tabs,
  Tag,
  Tooltip,
  Typography,
  Upload,
} from 'antd'
import {
  ArrowRightOutlined,
  CheckOutlined,
  ClearOutlined,
  DeleteOutlined,
  DownloadOutlined,
  LinkOutlined,
  LockOutlined,
  PlayCircleOutlined,
  ReloadOutlined,
  SafetyOutlined,
  ThunderboltOutlined,
  UnlockOutlined,
  UploadOutlined,
} from '@ant-design/icons'
import { useParams } from 'react-router-dom'
import {
  assetApi,
  downloadAiVideo,
  storyboardApi,
  videoGenApi,
} from '../api'
import type {
  ReferenceImage,
  StoryboardShot,
  VideoGenerationJob,
  VideoGenerationTemplate,
  VideoGenerationVersion,
} from '../api/types'

const { Title, Text, Paragraph } = Typography

const DURATION_OPTIONS = [5, 8, 10, 15]
const RATIO_OPTIONS = ['adaptive', '16:9', '9:16', '4:3', '3:4', '1:1', '21:9']
const RESOLUTION_OPTIONS = ['480p', '720p', '1080p']

const STATUS_MAP: Record<string, { label: string; color: string }> = {
  queued: { label: '排队中', color: 'blue' },
  running: { label: '生成中', color: 'processing' },
  success: { label: '成功', color: 'success' },
  failed: { label: '失败', color: 'error' },
  cancelled: { label: '已取消', color: 'default' },
}

const PROVIDER_LABELS: Record<string, string> = {
  seedance: '即梦 Seedance',
  minimax: 'MiniMax H3',
  mock: 'Mock 演示',
}

// 模板预览资源映射（按模板名称；来自 EVAI img2Video 抓取，2026-08-19）
const TEMPLATE_PREVIEWS: Record<string, { video: string; first: string; last?: string }> = {
  "建筑平移": { video: "/templates/01/preview.webm", first: "/templates/01/first.jpg" },
  "建筑鸟瞰环绕": { video: "/templates/02/preview.webm", first: "/templates/02/first.jpg" },
  "建筑从整体到局部": { video: "/templates/03/preview.webm", first: "/templates/03/first.jpg" },
  "建筑从室外到室内": { video: "/templates/04/preview.webm", first: "/templates/04/first.jpg" },
  "希区柯克推进": { video: "/templates/05/preview.webm", first: "/templates/05/first.jpg" },
  "中心环绕": { video: "/templates/06/preview.webm", first: "/templates/06/first.jpg" },
  "起重机": { video: "/templates/07/preview.webm", first: "/templates/07/first.jpg" },
  "超级拉远": { video: "/templates/08/preview.webm", first: "/templates/08/first.jpg" },
  "延时摄影": { video: "/templates/09/preview.webm", first: "/templates/09/first.jpg" },
  "俯瞰➕环绕": { video: "/templates/10/preview.webm", first: "/templates/10/first.jpg" },
  "推进+仰拍": { video: "/templates/11/preview.webm", first: "/templates/11/first.jpg" },
  "拉远": { video: "/templates/12/preview.webm", first: "/templates/12/first.jpg" },
  "建筑生长动画": { video: "/templates/13/preview.webm", first: "/templates/13/first.jpg", last: "/templates/13/last.jpg" },
  "城市生长动画": { video: "/templates/14/preview.webm", first: "/templates/14/first.jpg", last: "/templates/14/last.jpg" },
  "建筑像火箭一样升空": { video: "/templates/15/preview.webm", first: "/templates/15/first.jpg", last: "/templates/15/last.jpg" },
  "线稿转实景图": { video: "/templates/16/preview.webm", first: "/templates/16/first.jpg", last: "/templates/16/last.jpg" },
  "根据这张城市公园中的多层图书馆的建筑俯视图，生成对应的低空平视规划实景照片": { video: "/templates/17/preview.webm", first: "/templates/17/first.jpg", last: "/templates/17/last.jpg" },
  "视角转换": { video: "/templates/18/preview.webm", first: "/templates/18/first.jpg", last: "/templates/18/last.jpg" },
  "建筑工人施工将建筑的立面材质改为红砖": { video: "/templates/19/preview.webm", first: "/templates/19/first.jpg", last: "/templates/19/last.jpg" },
  "天气转变为大雾天气，固定视角，延时摄影": { video: "/templates/20/preview.webm", first: "/templates/20/first.jpg", last: "/templates/20/last.jpg" },
  "从白天到日落，固定视角，延时摄影": { video: "/templates/21/preview.webm", first: "/templates/21/first.jpg", last: "/templates/21/last.jpg" },
  "将图片中的氛围切换到夜晚，突出建筑内的灯光照明": { video: "/templates/22/preview.webm", first: "/templates/22/first.jpg", last: "/templates/22/last.jpg" },
  "图片中的天气切换为冬天，白雪覆盖建筑地面树木": { video: "/templates/23/preview.webm", first: "/templates/23/first.jpg", last: "/templates/23/last.jpg" },
  "变成微缩景观": { video: "/templates/24/preview.webm", first: "/templates/24/first.jpg", last: "/templates/24/last.jpg" },
  "白纸平整的置于桌面上，镜头快速由远景推近，紧接着环绕纸张进行旋转，以纸张为中心，线条开始如灵动的精灵般浮现交织，色彩逐渐晕染开来，随着镜头缓缓上升，画面中的线条与色彩不断汇聚、组合。建筑得轮廓逐渐清晰，最终画面定格在建筑图，这座宏伟的建筑完美呈现，仿佛从这张白纸之上拔地而起": { video: "/templates/25/preview.webm", first: "/templates/25/first.jpg", last: "/templates/25/last.jpg" },
  "变成微缩模型": { video: "/templates/26/preview.webm", first: "/templates/26/first.jpg", last: "/templates/26/last.jpg" },
  "街道翻新": { video: "/templates/27/preview.webm", first: "/templates/27/first.jpg", last: "/templates/27/last.jpg" },
  "根据手稿生成建筑": { video: "/templates/28/preview.webm", first: "/templates/28/first.jpg", last: "/templates/28/last.jpg" },
  "色彩从中心晕开": { video: "/templates/29/preview.webm", first: "/templates/29/first.jpg", last: "/templates/29/last.jpg" },
  "对建筑进行设计标注": { video: "/templates/30/preview.webm", first: "/templates/30/first.jpg", last: "/templates/30/last.jpg" },
  "生成建筑爆炸图": { video: "/templates/31/preview.webm", first: "/templates/31/first.jpg", last: "/templates/31/last.jpg" },
  "两名女士走到沙发上聊天": { video: "/templates/32/preview.webm", first: "/templates/32/first.jpg", last: "/templates/32/last.jpg" },
  "建筑工人对房屋进行翻新装修": { video: "/templates/33/preview.webm", first: "/templates/33/first.jpg", last: "/templates/33/last.jpg" },
  "生成建筑轴测模型": { video: "/templates/34/preview.webm", first: "/templates/34/first.jpg", last: "/templates/34/last.jpg" },
  "卡通人物走到沙发上交流": { video: "/templates/35/preview.webm", first: "/templates/35/first.jpg", last: "/templates/35/last.jpg" },
  "两个卡通人物走到咖啡厅门前喝咖啡": { video: "/templates/36/preview.webm", first: "/templates/36/first.jpg", last: "/templates/36/last.jpg" },
  "创建这座建筑的剖面图，一侧显示完整的外部结构，另一侧显示内部的结构以及装修细节。保持比例准确，细节逼真。": { video: "/templates/37/preview.webm", first: "/templates/37/first.jpg", last: "/templates/37/last.jpg" },
  "绘制一个 A6 折叠卡：打开时它会展示一个完整的 3D 球形小屋，里面有一座微型的纸花园和盆景树。": { video: "/templates/38/preview.webm", first: "/templates/38/first.jpg", last: "/templates/38/last.jpg" },
  "把这张建筑线稿图转成实景照片，要求摄影质感，真实的光影效果。阴天乌云密布，建筑里透出灯光，建筑前有零星的行人。保持画面结构不变。": { video: "/templates/39/preview.webm", first: "/templates/39/first.jpg", last: "/templates/39/last.jpg" },
  "将图片变真实": { video: "/templates/40/preview.webm", first: "/templates/40/first.jpg", last: "/templates/40/last.jpg" },
  "从红色圆圈沿箭头方向画出真实世界的视角": { video: "/templates/41/preview.webm", first: "/templates/41/first.jpg", last: "/templates/41/last.jpg" },
  "装修工人对房间进行布置": { video: "/templates/42/preview.webm", first: "/templates/42/first.jpg", last: "/templates/42/last.jpg" },
}


// 模型按钮样式
const modelButtonBase: CSSProperties = {
  padding: '7px 16px',
  borderRadius: 8,
  border: '1px solid #d9d9d9',
  background: '#fff',
  color: '#1f2937',
  cursor: 'pointer',
  fontSize: 13,
  fontWeight: 500,
  transition: 'all 0.2s',
}
const modelButtonActive: CSSProperties = {
  background: 'linear-gradient(135deg, #2563eb 0%, #7c3aed 100%)',
  color: '#fff',
  borderColor: 'transparent',
  boxShadow: '0 2px 10px rgba(99, 102, 241, 0.45)',
}

export default function AiVideo() {
  const { projectId = '' } = useParams()
  const { message } = App.useApp()

  const [refImages, setRefImages] = useState<ReferenceImage[]>([])
  const [templates, setTemplates] = useState<VideoGenerationTemplate[]>([])
  const [shots, setShots] = useState<StoryboardShot[]>([])
  const [tasks, setTasks] = useState<VideoGenerationJob[]>([])
  const [versions, setVersions] = useState<VideoGenerationVersion[]>([])

  const [generationMode, setGenerationMode] = useState<'image_to_video' | 'first_last_frame_video'>('first_last_frame_video')
  const [firstFrameId, setFirstFrameId] = useState<string>('')
  const [lastFrameId, setLastFrameId] = useState<string>('')

  const [selectedTemplateId, setSelectedTemplateId] = useState<string>('')
  const [prompt, setPrompt] = useState('')
  const [negativePrompt, setNegativePrompt] = useState('')
  const [constraintsEnabled, setConstraintsEnabled] = useState(true)
  const [seedLock, setSeedLock] = useState(false)
  const [seed, setSeed] = useState<number | null>(null)

  const [duration, setDuration] = useState(5)
  const [aspectRatio, setAspectRatio] = useState('adaptive')
  const [resolution, setResolution] = useState('720p')
  const [generateAudio, setGenerateAudio] = useState(false)
  const [modelName, setModelName] = useState('')
  const [providers, setProviders] = useState<any[]>([])
  const [selectedProvider, setSelectedProvider] = useState('')
  const [providerCaps, setProviderCaps] = useState<Record<string, boolean>>({})

  const [submitting, setSubmitting] = useState(false)
  const [masterLoading, setMasterLoading] = useState(false)
  const [activeJobId, setActiveJobId] = useState<string | null>(null)

  const [activeTab, setActiveTab] = useState('exterior')
  const [drawerOpen, setDrawerOpen] = useState(false)

  const [bindOpen, setBindOpen] = useState(false)
  const [bindVersion, setBindVersion] = useState<VideoGenerationVersion | null>(null)
  const [bindShotId, setBindShotId] = useState<string>('')

  const fetchAll = () => {
    Promise.all([
      videoGenApi.templates(projectId),
      videoGenApi.referenceImages(projectId),
      videoGenApi.listTasks(projectId),
      videoGenApi.versions(projectId),
      storyboardApi.list(projectId),
    ])
      .then(([t, r, j, v, s]) => {
        setTemplates(t.data)
        setRefImages(r.data)
        setTasks(j.data)
        setVersions(v.data)
        setShots(s.data)
      })
      .catch(() => {})
  }

  useEffect(() => {
    fetchAll()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [projectId])

  // Provider 信息与能力（即梦 Seedance / MiniMax 可切换）
  useEffect(() => {
    videoGenApi
      .providers(projectId)
      .then((res) => {
        const list = res.data || []
        setProviders(list)
        const def =
          list.find((p: any) => p.is_active && p.available) ||
          list.find((p: any) => p.available) ||
          list[0]
        if (def) {
          setSelectedProvider(def.provider)
          setProviderCaps(def.capabilities || {})
          setModelName(def.default_model || (def.models || [])[0] || '')
        }
      })
      .catch(() => {})
  }, [projectId])

  const currentProvider = useMemo(
    () => providers.find((p) => p.provider === selectedProvider) || null,
    [providers, selectedProvider],
  )

  const handleProviderChange = (provider: string) => {
    const p = providers.find((x) => x.provider === provider)
    setSelectedProvider(provider)
    setProviderCaps(p?.capabilities || {})
    setModelName(p?.default_model || (p?.models || [])[0] || '')
    if (p && p.capabilities?.first_last_frame_video !== true && generationMode === 'first_last_frame_video') {
      setGenerationMode('image_to_video')
      message.info(`${PROVIDER_LABELS[p.provider] || p.provider} 不支持首尾帧模式，已切换为图生视频`)
    }
    if (p && p.capabilities?.generate_audio !== true) {
      setGenerateAudio(false)
    }
  }

  // 任务轮询
  useEffect(() => {
    if (!activeJobId) return
    let stopped = false
    let timer: ReturnType<typeof setInterval>
    const tick = async () => {
      try {
        const response = await videoGenApi.getTask(projectId, activeJobId)
        if (stopped) return
        if (['success', 'failed', 'cancelled'].includes(response.data.status)) {
          clearInterval(timer)
          setActiveJobId(null)
          setSubmitting(false)
          fetchAll()
        }
      } catch {
        // 网络瞬时失败时继续轮询
      }
    }
    void tick()
    timer = setInterval(() => void tick(), 1500)
    return () => {
      stopped = true
      clearInterval(timer)
    }
  }, [activeJobId, projectId])

  const firstFrame = useMemo(() => refImages.find((i) => i.id === firstFrameId) || null, [refImages, firstFrameId])
  const lastFrame = useMemo(() => refImages.find((i) => i.id === lastFrameId) || null, [refImages, lastFrameId])

  const canFirstLast = providerCaps.first_last_frame_video === true
  const canImageToVideo = providerCaps.image_to_video !== false

  // 右侧分类：建筑外景运镜（单图图生）/ 首尾帧·创意运镜
  const displayTemplates = useMemo(() => {
    if (activeTab === 'creative') {
      return templates.filter((t) => (t.applicable_modes || []).includes('first_last_frame_video'))
    }
    return templates.filter((t) => (t.applicable_modes || []).includes('image_to_video'))
  }, [templates, activeTab])

  const runningCount = useMemo(
    () => tasks.filter((t) => ['queued', 'running', 'retry'].includes(t.status)).length,
    [tasks],
  )

  // 最终提交提示词预览（与后端 build_final_prompt 保持一致）
  const finalPromptPreview = useMemo(() => {
    const constraints = constraintsEnabled ? (templates.find((t) => t.id === selectedTemplateId)?.default_arch_constraints || []) : []
    const parts = [prompt.trim()]
    if (constraints.length) parts.push(constraints.join('；'))
    return parts.filter(Boolean).join('。')
  }, [prompt, constraintsEnabled, selectedTemplateId, templates])

  const handleUploadFrame = async (file: File) => {
    try {
      await assetApi.upload(projectId, file, file.name)
      message.success('参考帧已上传到素材库，请选择')
      videoGenApi.referenceImages(projectId).then((res) => setRefImages(res.data))
    } catch {
      // 拦截器已提示
    }
  }

  const handleSelectTemplate = (t: VideoGenerationTemplate) => {
    setSelectedTemplateId(t.id)
    setPrompt(t.default_positive_prompt || '')
    setNegativePrompt(t.default_negative_prompt || '')
    setDuration(t.recommended_duration)
    setAspectRatio(t.recommended_aspect_ratio)
    setResolution(t.recommended_resolution)
    setConstraintsEnabled(true)
    // 模板模式与左侧生成模式保持同步
    const tMode = (t.applicable_modes || []).includes('first_last_frame_video')
      ? 'first_last_frame_video'
      : 'image_to_video'
    if (tMode !== generationMode) {
      if (tMode === 'first_last_frame_video' && canFirstLast) {
        setGenerationMode('first_last_frame_video')
      } else {
        setGenerationMode('image_to_video')
      }
    }
  }

  // 提示词大师：读参考帧 + 用户意图，生成视频提示词
  const handlePromptMaster = async () => {
    const firstOk = !!firstFrameId
    const lastOk = generationMode === 'first_last_frame_video' ? !!lastFrameId : true
    if (!firstOk || !lastOk) {
      message.warning(generationMode === 'first_last_frame_video' ? '请先选择首帧与尾帧图片' : '请先选择一张参考帧图片')
      return
    }
    setMasterLoading(true)
    try {
      const res = await videoGenApi.promptMaster(projectId, {
        first_frame_asset_id: firstFrameId,
        last_frame_asset_id: generationMode === 'first_last_frame_video' ? lastFrameId : undefined,
        template_id: selectedTemplateId || undefined,
        intent: prompt.trim() || undefined,
        generation_mode: generationMode,
      })
      setPrompt(res.data.prompt)
      if (res.data.negative_prompt) setNegativePrompt(res.data.negative_prompt)
      message.success(res.data.is_mock ? '提示词已生成（演示模式）' : '提示词大师已生成')
    } catch {
      // 拦截器已提示
    } finally {
      setMasterLoading(false)
    }
  }

  const handleSubmit = async () => {
    if (!firstFrameId) {
      message.warning('请先在左侧明确选择一张首帧图片，再发起视频生成')
      return
    }
    if (generationMode === 'first_last_frame_video' && !lastFrameId) {
      message.warning('首尾帧模式必须明确选择两张图片：第一张为首帧，第二张为尾帧')
      return
    }
    if (!prompt.trim()) {
      message.warning('请填写视频提示词')
      return
    }

    // 建筑约束冲突预检
    try {
      const check = await videoGenApi.constraintCheck(projectId, prompt)
      if (check.data.blocked) {
        message.error('检测到可能改变工程结构的请求：' + check.data.conflicts.join('、') + '。禁止增加楼层、改变建筑轮廓、移动道路或替换主楼。')
        return
      }
    } catch {
      // 后端也会拦截
    }

    setSubmitting(true)
    setDrawerOpen(true)
    try {
      const res = await videoGenApi.createTask(projectId, {
        storyboard_shot_id: undefined,
        generation_mode: generationMode,
        first_frame_asset_id: firstFrameId,
        last_frame_asset_id: generationMode === 'first_last_frame_video' ? lastFrameId : undefined,
        template_id: selectedTemplateId || null,
        provider: selectedProvider || undefined,
        model_name: modelName || undefined,
        positive_prompt: prompt,
        negative_prompt: negativePrompt || null,
        duration,
        aspect_ratio: aspectRatio,
        resolution,
        seed: seedLock ? seed : null,
        generate_audio: generateAudio,
        constraints_enabled: constraintsEnabled,
        idempotency_key: `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
      })
      setActiveJobId(res.data.id)
      message.success('视频生成任务已提交')
      setTimeout(fetchAll, 1500)
    } catch {
      setSubmitting(false)
      // 拦截器已提示
    }
  }

  const handleSelectVersion = async (v: VideoGenerationVersion) => {
    try {
      await videoGenApi.selectVersion(projectId, v.id)
      message.success('已设为当前结果')
      fetchAll()
    } catch {
      // 拦截器已提示
    }
  }

  const handleBindShot = (v: VideoGenerationVersion) => {
    setBindVersion(v)
    setBindShotId('')
    setBindOpen(true)
  }

  const confirmBind = async () => {
    if (!bindVersion || !bindShotId) {
      message.warning('请选择要绑定的分镜')
      return
    }
    try {
      await videoGenApi.bindVersion(projectId, bindVersion.id, bindShotId)
      message.success('已绑定到分镜')
      setBindOpen(false)
      fetchAll()
    } catch {
      // 拦截器已提示
    }
  }

  const handleDeleteVersion = async (v: VideoGenerationVersion) => {
    try {
      await videoGenApi.deleteVersion(projectId, v.id)
      message.success('版本已删除')
      fetchAll()
    } catch {
      // 拦截器已提示
    }
  }

  const handleCancelJob = async (job: VideoGenerationJob) => {
    try {
      await videoGenApi.cancelTask(projectId, job.id)
      message.success('已取消任务')
      fetchAll()
    } catch {
      // 拦截器已提示
    }
  }

  const handleRetryJob = async (job: VideoGenerationJob) => {
    try {
      const res = await videoGenApi.retryTask(projectId, job.id)
      setActiveJobId(res.data.id)
      setSubmitting(true)
      fetchAll()
    } catch {
      // 拦截器已提示
    }
  }

  return (
    <div style={{ height: 'calc(100vh - 128px)', display: 'flex', gap: 16 }}>
      {/* ============ 左侧：生成控制面板 ============ */}
      <div
        style={{
          width: 360,
          flexShrink: 0,
          display: 'flex',
          flexDirection: 'column',
          background: '#fff',
          borderRadius: 12,
          border: '1px solid #f0f0f0',
          overflow: 'hidden',
        }}
      >
        <div style={{ flex: 1, overflowY: 'auto', padding: 16 }}>
          {/* 1. 功能标签 */}
          <Text strong style={{ fontSize: 14 }}>生成功能</Text>
          <Segmented
            block
            style={{ marginTop: 8 }}
            value={generationMode}
            onChange={(v) => setGenerationMode(String(v) as 'image_to_video' | 'first_last_frame_video')}
            options={[
              { label: '首尾帧视频', value: 'first_last_frame_video', disabled: !canFirstLast },
              { label: '多图视频', value: 'image_to_video', disabled: !canImageToVideo },
            ]}
          />
          {generationMode === 'first_last_frame_video' && !canFirstLast && (
            <Alert
              type="warning"
              showIcon
              style={{ marginTop: 8 }}
              message="当前模型不支持首尾帧，且不允许降级为普通图生视频"
            />
          )}

          {/* 2. 图片槽位 */}
          <Divider style={{ margin: '14px 0' }} />
          <Text strong style={{ fontSize: 14 }}>参考图片</Text>
          <div style={{ marginTop: 8 }}>
            {generationMode === 'first_last_frame_video' ? (
              <div style={{ display: 'flex', alignItems: 'flex-start', gap: 8 }}>
                <FrameSlot label="首帧" frame={firstFrame} images={refImages} onSelect={setFirstFrameId} onClear={() => setFirstFrameId('')} onUpload={handleUploadFrame} />
                <div style={{ paddingTop: 40, color: '#94a3b8', flexShrink: 0 }}>
                  <ArrowRightOutlined />
                </div>
                <FrameSlot label="尾帧" frame={lastFrame} images={refImages} onSelect={setLastFrameId} onClear={() => setLastFrameId('')} onUpload={handleUploadFrame} />
              </div>
            ) : (
              <FrameSlot label="参考图（首帧）" frame={firstFrame} images={refImages} onSelect={setFirstFrameId} onClear={() => setFirstFrameId('')} onUpload={handleUploadFrame} />
            )}
          </div>

          {/* 3. 模型类型（按钮式单选） */}
          <Divider style={{ margin: '14px 0' }} />
          <Text strong style={{ fontSize: 14 }}>模型类型</Text>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8, marginTop: 8 }}>
            {providers.map((p) => {
              const active = selectedProvider === p.provider
              return (
                <button
                  key={p.provider}
                  type="button"
                  disabled={!p.available}
                  onClick={() => handleProviderChange(p.provider)}
                  style={{
                    ...modelButtonBase,
                    ...(active ? modelButtonActive : {}),
                    ...(p.available ? {} : { opacity: 0.45, cursor: 'not-allowed' }),
                  }}
                  title={p.available ? undefined : '未配置 Key'}
                >
                  {PROVIDER_LABELS[p.provider] || p.provider}
                  {!p.available && '（未配置）'}
                </button>
              )
            })}
            {providers.length === 0 && <Text type="secondary" style={{ fontSize: 12 }}>暂无可用模型</Text>}
          </div>
          {currentProvider && (currentProvider.models?.length || 0) > 1 && (
            <div style={{ marginTop: 8 }}>
              <Text type="secondary" style={{ fontSize: 12 }}>模型版本：</Text>
              <Select
                size="small"
                style={{ width: '100%', marginTop: 4 }}
                value={modelName}
                onChange={setModelName}
                options={((currentProvider.models as string[]) || []).map((m) => ({ label: m, value: m }))}
              />
            </div>
          )}

          {/* 4. 模型说明 */}
          <div
            style={{
              marginTop: 10,
              background: '#f8fafc',
              borderRadius: 8,
              padding: '10px 12px',
              fontSize: 12,
              color: '#475569',
              lineHeight: 1.9,
            }}
          >
            <div><Text strong style={{ fontSize: 12, color: '#334155' }}>模型：</Text>{modelName || '—'}</div>
            <div>图生视频：{canImageToVideo ? '支持' : '不支持'}</div>
            <div>首尾帧过渡：{canFirstLast ? '支持' : '不支持'}</div>
            <div>生成声音：{providerCaps.generate_audio === true ? '支持（可关闭）' : '不支持'}</div>
            <div>视频时长：5 / 8 / 10 / 15 秒</div>
          </div>

          {/* 5. 输入描述 */}
          <Divider style={{ margin: '14px 0' }} />
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <Text strong style={{ fontSize: 14 }}>输入描述</Text>
          </div>
          <div style={{ position: 'relative', marginTop: 8 }}>
            <Input.TextArea
              rows={5}
              value={prompt}
              onChange={(e) => setPrompt(e.target.value)}
              placeholder="描述你想要的镜头与画面，例如：镜头缓慢推进，建筑主体稳定居中，光影自然"
              style={{ paddingRight: 92 }}
              maxLength={500}
            />
            <div
              style={{
                position: 'absolute',
                top: 8,
                right: 8,
                display: 'flex',
                flexDirection: 'column',
                alignItems: 'flex-end',
                gap: 4,
              }}
            >
              <Button
                size="small"
                type="primary"
                ghost
                icon={<ThunderboltOutlined />}
                loading={masterLoading}
                onClick={handlePromptMaster}
              >
                提示词大师
              </Button>
              <Text type="secondary" style={{ fontSize: 11 }}>
                {prompt.length} / 500
              </Text>
            </div>
          </div>

          {/* 6. 视频时长 */}
          <Divider style={{ margin: '14px 0' }} />
          <Text strong style={{ fontSize: 14 }}>视频时长</Text>
          <Segmented
            block
            style={{ marginTop: 8 }}
            value={duration}
            onChange={(v) => setDuration(Number(v))}
            options={DURATION_OPTIONS.map((d) => ({ label: `${d}S`, value: d }))}
          />

          {/* 高级参数 */}
          <div style={{ marginTop: 12 }}>
            <Collapse
              ghost
              size="small"
              items={[
                {
                  key: 'advanced',
                  label: '高级参数',
                  children: (
                    <div style={{ paddingTop: 4 }}>
                      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                        <Space align="center">
                          <Switch checked={constraintsEnabled} onChange={setConstraintsEnabled} checkedChildren={<SafetyOutlined />} unCheckedChildren={<SafetyOutlined />} />
                          <Text strong style={{ fontSize: 13 }}>建筑强约束（默认启用）</Text>
                        </Space>
                      </div>
                      {constraintsEnabled && (
                        <div style={{ marginTop: 8, fontSize: 12, color: '#666' }}>
                          {(templates.find((t) => t.id === selectedTemplateId)?.default_arch_constraints || []).length > 0
                            ? (templates.find((t) => t.id === selectedTemplateId)?.default_arch_constraints || []).join('；')
                            : '锁定建筑主体数量、体量、轮廓、层数；锁定道路、主入口、门窗、设备位置；禁止新增/删除主体与楼层等'}
                        </div>
                      )}

                      <Divider style={{ margin: '12px 0' }} />

                      <Space style={{ width: '100%', justifyContent: 'space-between' }} align="center">
                        <Space align="center">
                          <Switch
                            checked={seedLock}
                            onChange={(v) => {
                              setSeedLock(v)
                              if (!v) setSeed(null)
                            }}
                            checkedChildren={<LockOutlined />}
                            unCheckedChildren={<UnlockOutlined />}
                          />
                          <Text strong style={{ fontSize: 13 }}>随机种子锁定</Text>
                        </Space>
                        {seedLock && (
                          <InputNumber
                            style={{ width: 140 }}
                            size="small"
                            min={0}
                            value={seed}
                            onChange={(v) => setSeed(v)}
                            placeholder="固定种子"
                          />
                        )}
                      </Space>

                      <div style={{ display: 'flex', gap: 8, marginTop: 12 }}>
                        <div style={{ flex: 1 }}>
                          <Text type="secondary" style={{ fontSize: 12 }}>画面比例</Text>
                          <Select size="small" style={{ width: '100%', marginTop: 4 }} value={aspectRatio} onChange={setAspectRatio} options={RATIO_OPTIONS.map((r) => ({ label: r, value: r }))} />
                        </div>
                        <div style={{ flex: 1 }}>
                          <Text type="secondary" style={{ fontSize: 12 }}>分辨率</Text>
                          <Select size="small" style={{ width: '100%', marginTop: 4 }} value={resolution} onChange={setResolution} options={RESOLUTION_OPTIONS.map((r) => ({ label: r, value: r }))} />
                        </div>
                      </div>

                      <div style={{ marginTop: 12 }}>
                        <Space>
                          <Switch checked={generateAudio} onChange={setGenerateAudio} disabled={providerCaps.generate_audio !== true} size="small" />
                          <Text style={{ fontSize: 13 }}>生成声音</Text>
                          <Text type="secondary" style={{ fontSize: 11 }}>
                            {providerCaps.generate_audio === true ? '默认关闭，避免不可控音效' : '当前模型不支持'}
                          </Text>
                        </Space>
                      </div>

                      <div style={{ marginTop: 12 }}>
                        <Text type="secondary" style={{ fontSize: 12 }}>负向提示词（可选）</Text>
                        <Input.TextArea
                          rows={2}
                          style={{ marginTop: 4, fontSize: 13 }}
                          value={negativePrompt}
                          onChange={(e) => setNegativePrompt(e.target.value)}
                          placeholder="禁止内容，如：禁止改变建筑轮廓"
                        />
                      </div>

                      <div style={{ marginTop: 12 }}>
                        <Text type="secondary" style={{ fontSize: 12 }}>最终提交提示词预览</Text>
                        <div
                          style={{
                            marginTop: 4,
                            padding: 8,
                            background: '#fafafa',
                            border: '1px solid #f0f0f0',
                            borderRadius: 6,
                            fontSize: 12,
                            color: '#444',
                            minHeight: 40,
                            whiteSpace: 'pre-wrap',
                          }}
                        >
                          {finalPromptPreview || '（空）'}
                        </div>
                      </div>
                    </div>
                  ),
                },
              ]}
            />
          </div>
        </div>

        {/* 7. 底部主操作按钮 */}
        <div style={{ padding: '12px 16px', borderTop: '1px solid #f0f0f0', background: '#fff' }}>
          <Button
            block
            loading={submitting}
            onClick={handleSubmit}
            icon={<PlayCircleOutlined />}
            style={{
              height: 44,
              fontSize: 15,
              fontWeight: 600,
              border: 'none',
              background: 'linear-gradient(135deg, #2563eb 0%, #7c3aed 100%)',
              color: '#fff',
              boxShadow: '0 4px 14px rgba(99, 102, 241, 0.35)',
            }}
          >
            开始生成视频
          </Button>
        </div>
      </div>

      {/* ============ 右侧：视频模板素材库 ============ */}
      <div
        style={{
          flex: 1,
          overflowY: 'auto',
          background: '#fff',
          borderRadius: 12,
          border: '1px solid #f0f0f0',
          padding: '16px 20px 24px',
        }}
      >
        {/* 1. 标题区 */}
        <div className="page-header" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-end' }}>
          <div>
            <Title level={4} style={{ marginBottom: 2 }}>
              专业视频渲染引擎
            </Title>
            <Text type="secondary" style={{ fontSize: 13 }}>
              选择模板一键套用，或自定义提示词生成投标演示视频（独立提示词，不引用解说词）
            </Text>
          </div>
          <Tag color="geekblue" style={{ fontSize: 11, marginBottom: 4 }}>
            图生视频 · 首尾帧
          </Tag>
        </div>

        {/* 2. 分类 Tab */}
        <Tabs
          style={{ marginTop: 4 }}
          activeKey={activeTab}
          onChange={setActiveTab}
          items={[
            {
              key: 'exterior',
              label: <span style={{ fontWeight: 600 }}>建筑外景运镜</span>,
            },
            {
              key: 'creative',
              label: (
                <span style={{ fontWeight: 600 }}>
                  首尾帧·创意运镜
                  <Tag color="volcano" style={{ fontSize: 10, lineHeight: '16px', marginInlineStart: 6 }}>
                    NEW
                  </Tag>
                </span>
              ),
            },
          ]}
        />

        {/* 3. 模板瀑布 / 网格 */}
        {displayTemplates.length === 0 && <Empty description="当前分类暂无模板" style={{ marginTop: 40 }} />}
        <Row gutter={[16, 16]}>
          {displayTemplates.map((t) => {
            const preview = TEMPLATE_PREVIEWS[t.name] || {}
            const isFL = (t.applicable_modes || []).includes('first_last_frame_video')
            const selected = selectedTemplateId === t.id
            return (
              <Col xs={24} md={12} lg={8} key={t.id}>
                <Card
                  hoverable
                  onClick={() => handleSelectTemplate(t)}
                  styles={{ body: { padding: '12px 14px', display: 'flex', flexDirection: 'column', flex: 1 } }}
                  style={{
                    borderRadius: 12,
                    overflow: 'hidden',
                    height: '100%',
                    display: 'flex',
                    flexDirection: 'column',
                    border: selected ? '1.5px solid #6366f1' : '1px solid #f0f0f0',
                    boxShadow: selected ? '0 4px 16px rgba(99, 102, 241, 0.18)' : undefined,
                  }}
                  cover={<TemplatePreview t={t} preview={preview} isFL={isFL} />}
                >
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: 8, flexShrink: 0 }}>
                    <Text strong style={{ fontSize: 14, flex: 1, minWidth: 0 }} ellipsis={{ tooltip: t.name }}>{t.name}</Text>
                    {isFL && <Tag color="purple" style={{ fontSize: 10, marginInlineEnd: 0, flexShrink: 0 }}>首尾帧</Tag>}
                  </div>
                  <Paragraph
                    type="secondary"
                    style={{ fontSize: 12, marginTop: 6, marginBottom: 0, lineHeight: '20px', minHeight: 40, flex: 1 }}
                    ellipsis={{ rows: 2, tooltip: t.description }}
                  >
                    {t.description}
                  </Paragraph>
                  <div style={{ marginTop: 8, flexShrink: 0 }}>
                    {t.recommended_camera_motion && (
                      <Tag style={{ fontSize: 11, color: '#475569' }}>{t.recommended_camera_motion}</Tag>
                    )}
                    <Tag style={{ fontSize: 11, color: '#475569' }}>{t.recommended_duration}s</Tag>
                  </div>
                </Card>
              </Col>
            )
          })}
        </Row>
      </div>

      {/* ============ 生成任务与结果（抽屉） ============ */}
      <Drawer
        title="生成任务与结果"
        placement="right"
        width={440}
        open={drawerOpen}
        onClose={() => setDrawerOpen(false)}
      >
        <Text strong>任务状态</Text>
        {tasks.length === 0 && <Empty description="暂无任务" style={{ marginTop: 12 }} />}
        <List
          size="small"
          dataSource={tasks.slice(0, 8)}
          renderItem={(t) => {
            const st = STATUS_MAP[t.status] || { label: t.status, color: 'default' }
            return (
              <List.Item style={{ display: 'block', padding: '6px 0' }}>
                <Space style={{ width: '100%', justifyContent: 'space-between' }}>
                  <Space size={6}>
                    <Tag color={st.color} style={{ fontSize: 11 }}>{st.label}</Tag>
                    <Text style={{ fontSize: 12 }}>{t.generation_mode === 'first_last_frame_video' ? '首尾帧' : '多图/图生'} · {t.progress}%</Text>
                  </Space>
                  <Text type="secondary" style={{ fontSize: 11 }}>
                    {t.elapsed_seconds ? `${t.elapsed_seconds}s` : ''} {PROVIDER_LABELS[t.provider] || t.provider}
                  </Text>
                </Space>
                {(t.status === 'queued' || t.status === 'running') && (
                  <Progress percent={t.progress} size="small" style={{ margin: '4px 0 0' }} />
                )}
                {t.status === 'failed' && (
                  <Tooltip title={t.error_message}>
                    <Text type="danger" style={{ fontSize: 11, display: 'block' }} ellipsis>
                      {t.error_message}
                    </Text>
                  </Tooltip>
                )}
                {t.status === 'running' && (
                  <Button size="small" danger style={{ marginTop: 4 }} onClick={() => handleCancelJob(t)}>
                    取消
                  </Button>
                )}
                {t.status === 'failed' && (
                  <Button size="small" icon={<ReloadOutlined />} style={{ marginTop: 4 }} onClick={() => handleRetryJob(t)}>
                    重试
                  </Button>
                )}
              </List.Item>
            )
          }}
        />

        <Divider style={{ margin: '16px 0' }} />

        <Text strong>视频结果版本</Text>
        {versions.length === 0 && <Empty description="暂无结果版本" style={{ marginTop: 12 }} />}
        <div style={{ marginTop: 8, display: 'flex', flexDirection: 'column', gap: 8 }}>
          {versions.map((v) => (
            <Card key={v.id} size="small">
              <div style={{ position: 'relative' }}>
                {v.result_url ? (
                  <video
                    src={v.result_url}
                    style={{ width: '100%', height: 140, objectFit: 'cover', borderRadius: 4, background: '#000' }}
                    controls
                    preload="metadata"
                  />
                ) : (
                  <div style={{ width: '100%', height: 140, background: '#f5f5f5', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
                    <Text type="secondary">V{v.version_number}</Text>
                  </div>
                )}
                {v.is_selected && (
                  <Tag color="green" style={{ position: 'absolute', top: 4, right: 4, fontSize: 10 }}>
                    当前结果
                  </Tag>
                )}
              </div>
              <Space style={{ marginTop: 6, width: '100%', justifyContent: 'space-between' }}>
                <Text strong style={{ fontSize: 12 }}>V{v.version_number}</Text>
                <Text type="secondary" style={{ fontSize: 10 }}>
                  seed:{v.seed ?? '-'} · {PROVIDER_LABELS[v.provider] || v.provider}
                </Text>
              </Space>
              {v.bound_shot_title && (
                <div style={{ marginTop: 4 }}>
                  <Tag color="blue" icon={<LinkOutlined />} style={{ fontSize: 10 }}>
                    已绑定：{v.bound_shot_title}
                  </Tag>
                </div>
              )}
              <Space style={{ marginTop: 6 }} wrap>
                {v.result_url && (
                  <Button size="small" icon={<DownloadOutlined />} onClick={() => downloadAiVideo(v.result_url!)}>
                    下载
                  </Button>
                )}
                <Button
                  size="small"
                  type={v.is_selected ? 'default' : 'primary'}
                  icon={<CheckOutlined />}
                  onClick={() => handleSelectVersion(v)}
                >
                  设为当前
                </Button>
                <Button size="small" icon={<LinkOutlined />} onClick={() => handleBindShot(v)}>
                  绑定分镜
                </Button>
                <Button size="small" danger icon={<DeleteOutlined />} onClick={() => handleDeleteVersion(v)}>
                  删除
                </Button>
              </Space>
            </Card>
          ))}
        </div>
      </Drawer>

      {/* 悬浮入口：生成记录 */}
      <FloatButton
        icon={<PlayCircleOutlined />}
        badge={runningCount ? { count: runningCount, color: '#7c3aed' } : undefined}
        onClick={() => setDrawerOpen(true)}
        tooltip="生成任务与结果"
        style={{ right: 28, bottom: 28 }}
      />

      {/* 绑定分镜弹窗 */}
      <Modal
        title="绑定视频到分镜"
        open={bindOpen}
        onCancel={() => setBindOpen(false)}
        onOk={confirmBind}
        okText="绑定"
      >
        <Alert
          type="info"
          showIcon
          style={{ marginBottom: 12 }}
          message="将当前视频手动绑定到某个分镜。绑定不会修改解说词，也不影响已配置的视频任务。"
        />
        <Select
          style={{ width: '100%' }}
          placeholder="选择分镜"
          value={bindShotId || undefined}
          onChange={setBindShotId}
          options={shots.map((s) => ({
            value: s.id,
            label: `#${s.sequence} ${s.title || '（无标题）'}`,
          }))}
        />
      </Modal>
    </div>
  )
}

// 参考帧槽位（选择 / 上传 / 清空 / 预览）
function FrameSlot({
  label,
  frame,
  images,
  onSelect,
  onClear,
  onUpload,
}: {
  label: string
  frame: ReferenceImage | null
  images: ReferenceImage[]
  onSelect: (id: string) => void
  onClear: () => void
  onUpload: (file: File) => void
}) {
  return (
    <div style={{ flex: 1, minWidth: 0 }}>
      <Text strong style={{ fontSize: 12, color: '#475569' }}>{label}</Text>
      <div
        style={{
          marginTop: 6,
          position: 'relative',
          height: 92,
          borderRadius: 8,
          border: '1px dashed #d9d9d9',
          overflow: 'hidden',
          background: '#fafafa',
        }}
      >
        {frame ? (
          <>
            <img src={frame.url} alt={frame.name} style={{ width: '100%', height: '100%', objectFit: 'cover' }} />
            <Button size="small" icon={<ClearOutlined />} style={{ position: 'absolute', top: 4, right: 4 }} onClick={onClear} />
          </>
        ) : (
          <div style={{ width: '100%', height: '100%', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
            <Text type="secondary" style={{ fontSize: 12 }}>未选择{label}</Text>
          </div>
        )}
      </div>
      <Space style={{ marginTop: 6, width: '100%' }}>
        <Select
          size="small"
          style={{ flex: 1, minWidth: 0 }}
          placeholder="选择"
          value={frame?.id}
          onChange={onSelect}
          showSearch
          optionFilterProp="label"
          options={images.map((i) => ({ value: i.id, label: i.name }))}
        />
        <Upload
          accept=".jpg,.jpeg,.png,.webp"
          showUploadList={false}
          beforeUpload={(file) => {
            onUpload(file)
            return false
          }}
        >
          <Button size="small" icon={<UploadOutlined />}>
            上传
          </Button>
        </Upload>
      </Space>
    </div>
  )
}

// 模板卡片预览区（视频占位 + 左下角首尾帧缩略图）
function TemplatePreview({
  t,
  preview,
  isFL,
}: {
  t: VideoGenerationTemplate
  preview: { video?: string; first?: string; last?: string }
  isFL: boolean
}) {
  return (
    <div
      style={{
        position: 'relative',
        height: 160,
        background: 'linear-gradient(135deg, #eef2ff 0%, #f5f3ff 100%)',
        overflow: 'hidden',
      }}
    >
      {preview.video ? (
        <video
          src={preview.video}
          poster={preview.first}
          style={{ width: '100%', height: '100%', objectFit: 'cover' }}
          muted
          loop
          playsInline
          preload="metadata"
          onMouseEnter={(e) => e.currentTarget.play().catch(() => {})}
          onMouseLeave={(e) => {
            const v = e.currentTarget
            v.pause()
            v.currentTime = 0
          }}
        />
      ) : (
        <div
          style={{
            width: '100%',
            height: '100%',
            display: 'flex',
            flexDirection: 'column',
            alignItems: 'center',
            justifyContent: 'center',
            gap: 6,
            color: '#8b93a7',
          }}
        >
          <PlayCircleOutlined style={{ fontSize: 36, color: '#a5b0c7' }} />
          <Text style={{ fontSize: 12, color: '#8b93a7' }}>预览视频待补充</Text>
          <Text style={{ fontSize: 11, color: '#a5adbd' }}>{t.recommended_camera_motion || ''}</Text>
        </div>
      )}

      {/* 左下角首尾帧缩略图（hover 放大） */}
      <div style={{ position: 'absolute', left: 8, bottom: 8, display: 'flex', alignItems: 'flex-end', gap: 5 }}>
        <Thumb url={preview.first} label="首" origin="left bottom" />
        {isFL && <ArrowRightOutlined style={{ color: '#fff', fontSize: 12, marginBottom: 9 }} />}
        {isFL && <Thumb url={preview.last} label="尾" origin="right bottom" />}
      </div>

      {/* 时长角标 */}
      <Tag style={{ position: 'absolute', right: 8, top: 8, fontSize: 11 }}>{t.recommended_duration}s</Tag>
    </div>
  )
}

function Thumb({ url, label, origin = 'left bottom' }: { url?: string; label: string; origin?: string }) {
  const [hover, setHover] = useState(false)
  return url ? (
    <div
      onMouseEnter={() => setHover(true)}
      onMouseLeave={() => setHover(false)}
      style={{
        width: 36,
        height: 36,
        borderRadius: 6,
        border: '2px solid #fff',
        boxShadow: hover ? '0 6px 20px rgba(0,0,0,0.45)' : '0 1px 4px rgba(0,0,0,0.2)',
        overflow: 'hidden',
        position: 'relative',
        zIndex: hover ? 10 : 1,
        transform: hover ? 'scale(2.4)' : 'scale(1)',
        transformOrigin: origin,
        transition: 'transform .18s ease, boxShadow .18s ease',
        cursor: 'zoom-in',
        flexShrink: 0,
      }}
    >
      <img src={url} alt={label} style={{ width: '100%', height: '100%', objectFit: 'cover', display: 'block' }} />
    </div>
  ) : (
    <div
      style={{
        width: 36,
        height: 36,
        borderRadius: 6,
        border: '2px solid #fff',
        background: 'rgba(30, 41, 59, 0.5)',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        color: '#fff',
        fontSize: 11,
        fontWeight: 600,
        flexShrink: 0,
      }}
    >
      {label}
    </div>
  )
}
