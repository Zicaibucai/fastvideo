import { useEffect, useMemo, useState } from 'react'
import type { CSSProperties } from 'react'
import {
  Alert,
  App,
  Button,
  Card,
  Col,
  Collapse,
  Divider,
  Drawer,
  Empty,
  Input,
  InputNumber,
  Modal,
  Popconfirm,
  Progress,
  Row,
  Segmented,
  Select,
  Space,
  Switch,
  Tabs,
  Tag,
  Typography,
  Upload,
} from 'antd'
import {
  ArrowRightOutlined,
  CheckCircleOutlined,
  CheckOutlined,
  ClearOutlined,
  DeleteOutlined,
  DownloadOutlined,
  EditOutlined,
  LockOutlined,
  PlayCircleOutlined,
  ReloadOutlined,
  SafetyOutlined,
  ThunderboltOutlined,
  UnlockOutlined,
  UploadOutlined,
} from '@ant-design/icons'
import { useLocation, useNavigate, useParams } from 'react-router-dom'
import {
  assetApi,
  downloadAiVideo,
  videoGenApi,
} from '../api'
import { withAuthToken } from '../api/client'
import type {
  ReferenceImage,
  VideoGenerationJob,
  VideoGenerationTemplate,
  VideoGenerationVersion,
} from '../api/types'
import { readAiVideoDraft, saveAiVideoDraft } from '../utils/aiVideoDraft'

const { Title, Text, Paragraph } = Typography

const DURATION_OPTIONS = [5, 8, 10, 15]
const RATIO_OPTIONS = ['adaptive', '16:9', '9:16', '4:3', '3:4', '1:1', '21:9']
const RESOLUTION_OPTIONS = ['480p', '720p', '1080p']
const normalizeResolution = (value: any, fallback = '720p') => {
  const normalized = String(value || '').trim().toLowerCase()
  return RESOLUTION_OPTIONS.includes(normalized) ? normalized : fallback
}

// 分辨率由高级参数控制。提示词大师可能把“4K/超高清”等自然语言混进
// 镜头描述，先清掉这些冲突词，再交给后端按 resolution 编译。
const sanitizePromptResolution = (value: string) => {
  let text = String(value || '').trim()
  if (!text) return ''
  const hadResolutionMention = /(?:分辨率|清晰度)\s*(?:为|是|设为|设置为|[:：=])?\s*(?:8k|4k|2k|1080p|720p|480p|超高清|高清)(?:画质|分辨率)?|(?:8k|4k|2k|1080p|720p|480p)\s*(?:画质|分辨率)?|(?:超高清|高清)(?:画质|分辨率)/i.test(text)
  if (!hadResolutionMention) return text
  text = text
    .replace(/(?:分辨率|清晰度)\s*(?:为|是|设为|设置为|[:：=])?\s*(?:8k|4k|2k|1080p|720p|480p|超高清|高清)(?:画质|分辨率)?/gi, '')
    .replace(/(?:8k|4k|2k|1080p|720p|480p)\s*(?:画质|分辨率)?/gi, '')
    .replace(/(?:超高清|高清)(?:画质|分辨率)/gi, '')
    .replace(/[（(]\s*[）)]/g, '')
    .replace(/([，,；;。])\s*([，,；;。])+/g, '$1')
    .replace(/\s{2,}/g, ' ')
  return text.replace(/^[，,；;。\s]+|[，,；;。\s]+$/g, '').trim()
}

const PROVIDER_LABELS: Record<string, string> = {
  seedance: '即梦 Seedance',
  minimax: '历史视频通道',
  mock: '本地演示',
}

const templateAssetUrl = (fileKey?: string) => (fileKey ? withAuthToken(`/files/${fileKey}`) : undefined)

const templateMode = (template: VideoGenerationTemplate) => {
  const modes = template.applicable_modes || []
  if (modes.includes('first_last_frame_video')) return 'first_last_frame_video' as const
  if (modes.includes('multi_reference_video')) return 'multi_reference_video' as const
  return 'image_to_video' as const
}

// 多图模板可以复用提示词与参数，但不强制切换当前生成通道。
// 默认仍是首尾帧；只有用户主动选择多参考图时才使用多参考图。
const isFlexibleReferenceTemplate = (template: VideoGenerationTemplate) =>
  (template.applicable_modes || []).includes('multi_reference_video')

const templateSupportsMode = (template: VideoGenerationTemplate, mode: string) => {
  const modes = template.applicable_modes || []
  if (isFlexibleReferenceTemplate(template)) return true
  if (modes.includes(mode)) return true
  // 旧的单图模板仍允许在 Seedance 2.0 中扩展为多参考图。
  return mode === 'multi_reference_video' && modes.includes('image_to_video')
}

const templateReferenceCount = (template: VideoGenerationTemplate) => {
  if (template.reference_frame_count && template.reference_frame_count > 0) return Math.min(9, template.reference_frame_count)
  const modes = template.applicable_modes || []
  if (modes.includes('multi_reference_video')) return 3
  if (modes.includes('first_last_frame_video')) return 2
  return 1
}

const templatePrompt = (template: VideoGenerationTemplate) => {
  const recipePrompt = template.prompt_recipe?.prompt
  return typeof recipePrompt === 'string' && recipePrompt.trim()
    ? recipePrompt
    : template.default_positive_prompt || ''
}

const isConstructionRecipe = (recipe: Record<string, any> | null) => Boolean(
  recipe && (
    Number(recipe.recipe_version || 0) >= 2
    || recipe.construction_mode === 'construction_evolution'
    || recipe.project_facts
    || recipe.construction_unit
  ),
)

/**
 * 视觉模型偶尔会把结构化结果放进 prompt 字段，或在 JSON 外包一层 Markdown/说明文字。
 * 快速生成页只展示可直接投喂的 prompt；其余字段留给施工工作台的分栏编辑器。
 */
const parsePromptMasterPayload = (data: Record<string, any> | null | undefined) => {
  const source = data || {}
  const directPrompt = typeof source.prompt === 'string' ? source.prompt.trim() : ''
  let structured: Record<string, any> | null = null
  const candidates = [directPrompt, typeof source.raw_prompt === 'string' ? source.raw_prompt.trim() : '']
  for (const candidate of candidates) {
    if (!candidate || !(/[{}]/.test(candidate))) continue
    const clean = candidate
      .replace(/^\s*```(?:json)?\s*/i, '')
      .replace(/\s*```\s*$/i, '')
      .trim()
    const start = clean.indexOf('{')
    const end = clean.lastIndexOf('}')
    if (start < 0 || end <= start) continue
    try {
      const parsed = JSON.parse(clean.slice(start, end + 1))
      if (parsed && typeof parsed === 'object' && !Array.isArray(parsed)) {
        structured = parsed
        break
      }
    } catch {
      // 模型返回普通文本时继续使用原始 prompt。
    }
  }
  const recipe = source.recipe && typeof source.recipe === 'object'
    ? source.recipe
    : structured?.recipe && typeof structured.recipe === 'object'
      ? structured.recipe
      : null
  const prompt = String(structured?.prompt || directPrompt || '').trim()
  const negativePrompt = String(source.negative_prompt || structured?.negative_prompt || '').trim()
  return {
    prompt,
    negativePrompt,
    recipe,
    name: String(source.name || structured?.name || '').trim(),
    description: String(source.description || structured?.description || '').trim(),
  }
}

const recipeDuration = (value: any, fallback = 5) => {
  const numbers = String(value ?? '').match(/\d+(?:\.\d+)?/g)?.map(Number) || []
  if (!numbers.length) return fallback
  const selected = numbers.length > 1 ? (numbers[0] + numbers[1]) / 2 : numbers[0]
  return Math.max(2, Math.min(15, Math.round(selected)))
}

const expandRecipePrompt = (prompt: string, recipe: Record<string, any> | null) => {
  if (!recipe) return prompt.trim()
  const parts = [prompt.trim()]
  const camera = recipe.camera
  if (camera && typeof camera === 'object') {
    const fields = [
      camera.type ? `类型：${camera.type}` : '',
      camera.direction ? `方向：${camera.direction}` : '',
      camera.path ? `路径：${camera.path}` : '',
      camera.speed ? `速度：${camera.speed}` : '',
      camera.intensity ? `强度：${camera.intensity}` : '',
    ].filter(Boolean)
    if (fields.length) parts.push(`运镜设定：${fields.join('；')}`)
  } else if (camera) {
    parts.push(`运镜设定：${String(camera)}`)
  }
  if (Array.isArray(recipe.timeline) && recipe.timeline.length) {
    const timeline = recipe.timeline
      .map((item: any) => `${item.from ?? 0}%-${item.to ?? 100}%：${item.instruction || item.description || ''}`)
      .filter(Boolean)
      .join('；')
    if (timeline) parts.push(`时间轴：${timeline}`)
  } else if (recipe.timeline) {
    parts.push(`时间轴：${String(recipe.timeline)}`)
  }
  if (Array.isArray(recipe.reference_timing_seconds) && recipe.reference_timing_seconds.length) {
    const timing = recipe.reference_timing_seconds
      .map((value: any, index: number) => {
        const seconds = Number(value)
        return Number.isFinite(seconds) ? `第${index + 1}张=${seconds.toFixed(3)}s` : ''
      })
      .filter(Boolean)
      .join('；')
    if (timing) {
      const duration = Number(recipe.clip_duration_seconds)
      const durationText = Number.isFinite(duration) ? `，总时长${duration.toFixed(3)}s` : ''
      parts.push(`参考图时序（从当前镜头起点0秒计算，不使用原视频绝对时间${durationText}）：${timing}`)
    }
  }
  const list = (value: any) => Array.isArray(value) ? value.filter(Boolean).join('；') : value ? String(value) : ''
  if (list(recipe.preserve)) parts.push(`建筑保持项（必须锁定）：${list(recipe.preserve)}`)
  if (list(recipe.allow_change)) parts.push(`允许变化项（仅限这些变化）：${list(recipe.allow_change)}`)
  return parts.filter(Boolean).join('。')
}

const versionDisplayName = (version: VideoGenerationVersion) =>
  version.name?.trim() || `AI视频 V${version.version_number}`

const versionDownloadName = (version: VideoGenerationVersion) => {
  const name = versionDisplayName(version)
  return /\.[a-z0-9]{2,8}$/i.test(name) ? name : `${name}.mp4`
}

const formatImageDimensions = (width?: number, height?: number) => (
  Number.isFinite(width) && Number(width) > 0 && Number.isFinite(height) && Number(height) > 0
    ? `${width} × ${height}`
    : ''
)

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
  background: '#2457A6',
  color: '#fff',
  borderColor: '#2457A6',
  boxShadow: '0 2px 6px rgba(36, 87, 166, 0.16)',
}

export default function AiVideo() {
  const { projectId = '' } = useParams()
  const navigate = useNavigate()
  const location = useLocation()
  const { message } = App.useApp()
  const [initialDraft] = useState(() => readAiVideoDraft(projectId) || {})
  // 兼容旧草稿：早期版本可能把提示词大师返回的完整 JSON 保存进了 prompt。
  const initialPromptPayload = parsePromptMasterPayload({
    prompt: initialDraft.prompt,
    negative_prompt: initialDraft.negativePrompt,
    recipe: initialDraft.recipe,
  })

  const [refImages, setRefImages] = useState<ReferenceImage[]>([])
  const [templates, setTemplates] = useState<VideoGenerationTemplate[]>([])
  const [versions, setVersions] = useState<VideoGenerationVersion[]>([])

  const [generationMode, setGenerationMode] = useState<'image_to_video' | 'first_last_frame_video' | 'multi_reference_video'>(initialDraft.generationMode || 'first_last_frame_video')
  const [firstFrameId, setFirstFrameId] = useState<string>(initialDraft.firstFrameId || '')
  const [lastFrameId, setLastFrameId] = useState<string>(initialDraft.lastFrameId || '')
  const [referenceAssetIds, setReferenceAssetIds] = useState<string[]>(initialDraft.referenceAssetIds || [])

  const [selectedTemplateId, setSelectedTemplateId] = useState<string>(initialDraft.selectedTemplateId || '')
  const [prompt, setPrompt] = useState(sanitizePromptResolution(initialPromptPayload.prompt || initialDraft.prompt || ''))
  const [negativePrompt, setNegativePrompt] = useState(initialPromptPayload.negativePrompt || initialDraft.negativePrompt || '')
  const [promptRecipe, setPromptRecipe] = useState<Record<string, any> | null>(initialPromptPayload.recipe || initialDraft.recipe || null)
  const [advancedEnabled, setAdvancedEnabled] = useState(initialDraft.advancedEnabled === true)
  const [compiledPromptPreview, setCompiledPromptPreview] = useState('')
  const [constraintsEnabled, setConstraintsEnabled] = useState(initialDraft.constraintsEnabled ?? true)
  const [seedLock, setSeedLock] = useState(initialDraft.seedLock ?? false)
  const [seed, setSeed] = useState<number | null>(initialDraft.seed ?? null)

  const [duration, setDuration] = useState(initialDraft.duration || 5)
  const [aspectRatio, setAspectRatio] = useState(initialDraft.aspectRatio || 'adaptive')
  const [resolution, setResolution] = useState(normalizeResolution(initialDraft.resolution))
  const [generateAudio, setGenerateAudio] = useState(initialDraft.generateAudio ?? false)
  const [modelName, setModelName] = useState(initialDraft.modelName || '')
  const [providers, setProviders] = useState<any[]>([])
  const [selectedProvider, setSelectedProvider] = useState('seedance')
  const [providerCaps, setProviderCaps] = useState<Record<string, boolean>>({})

  const [submitting, setSubmitting] = useState(false)
  const [masterLoading, setMasterLoading] = useState(false)
  const [activeJobId, setActiveJobId] = useState<string | null>(null)
  const [activeJob, setActiveJob] = useState<VideoGenerationJob | null>(null)

  const [activeTab, setActiveTab] = useState('exterior')
  const [drawerOpen, setDrawerOpen] = useState(false)
  const [templateScopeFilter, setTemplateScopeFilter] = useState<'all' | 'personal' | 'organization'>('all')
  const [templateToApply, setTemplateToApply] = useState<VideoGenerationTemplate | null>(null)
  const [templateApplyOpen, setTemplateApplyOpen] = useState(false)
  const [deletingTemplateId, setDeletingTemplateId] = useState<string | null>(null)
  const [applyFirstFrameId, setApplyFirstFrameId] = useState('')
  const [applyLastFrameId, setApplyLastFrameId] = useState('')
  const [applyReferenceIds, setApplyReferenceIds] = useState<string[]>([])
  const [applySubject, setApplySubject] = useState('')
  const [applyScene, setApplyScene] = useState('')

  const [renameVersionTarget, setRenameVersionTarget] = useState<VideoGenerationVersion | null>(null)
  const [renameVersionValue, setRenameVersionValue] = useState('')
  const [renamingVersion, setRenamingVersion] = useState(false)

  // V2 施工配方只在工作台确认应用后生效；普通快速生成不继承历史高级草稿。
  const activePromptRecipe = isConstructionRecipe(promptRecipe) && !advancedEnabled
    ? null
    : promptRecipe

  useEffect(() => {
    const incoming = (location.state || {}) as Record<string, any>
    if (incoming.submittedJob?.id) {
      setActiveJob(incoming.submittedJob)
      setActiveJobId(incoming.submittedJob.id)
    }
    // 回到快速生成页时，先应用工作台的开关状态；即使没有携带配方，也不能
    // 让上一次已经应用的高级状态残留在本次普通快速生成里。
    if (typeof incoming.advancedEnabled === 'boolean') setAdvancedEnabled(incoming.advancedEnabled)
    if (!incoming.recipe && typeof incoming.prompt !== 'string') return
    const incomingPromptPayload = parsePromptMasterPayload({
      prompt: incoming.prompt,
      negative_prompt: incoming.negativePrompt,
      recipe: incoming.recipe,
    })
    if (incomingPromptPayload.recipe) setPromptRecipe(incomingPromptPayload.recipe)
    if (typeof incoming.prompt === 'string') setPrompt(sanitizePromptResolution(incomingPromptPayload.prompt))
    if (typeof incoming.negativePrompt === 'string' || incomingPromptPayload.negativePrompt) {
      setNegativePrompt(incomingPromptPayload.negativePrompt)
    }
    setSelectedProvider('seedance')
    if (typeof incoming.modelName === 'string') setModelName(incoming.modelName)
    if (typeof incoming.duration === 'number') setDuration(incoming.duration)
    if (typeof incoming.firstFrameId === 'string') setFirstFrameId(incoming.firstFrameId)
    if (typeof incoming.lastFrameId === 'string') setLastFrameId(incoming.lastFrameId)
    if (Array.isArray(incoming.referenceAssetIds)) setReferenceAssetIds(incoming.referenceAssetIds)
    if (typeof incoming.selectedTemplateId === 'string') setSelectedTemplateId(incoming.selectedTemplateId)
    if (['image_to_video', 'first_last_frame_video', 'multi_reference_video'].includes(incoming.generationMode)) setGenerationMode(incoming.generationMode)
    if (typeof incoming.aspectRatio === 'string') setAspectRatio(incoming.aspectRatio)
    if (typeof incoming.resolution === 'string') setResolution(normalizeResolution(incoming.resolution, resolution))
    if (typeof incoming.generateAudio === 'boolean') setGenerateAudio(incoming.generateAudio)
    if (typeof incoming.constraintsEnabled === 'boolean') setConstraintsEnabled(incoming.constraintsEnabled)
    if (typeof incoming.seedLock === 'boolean') setSeedLock(incoming.seedLock)
    if (typeof incoming.seed === 'number' || incoming.seed === null) setSeed(incoming.seed)
  }, [location.state])

  useEffect(() => {
    const timer = window.setTimeout(() => saveAiVideoDraft(projectId, {
      recipe: promptRecipe,
      advancedEnabled,
      prompt,
      negativePrompt,
      selectedProvider: 'seedance',
      modelName,
      duration,
      firstFrameId,
      lastFrameId,
      referenceAssetIds,
      selectedTemplateId,
      generationMode,
      aspectRatio,
      resolution,
      generateAudio,
      constraintsEnabled,
      seedLock,
      seed,
    }), 220)
    return () => window.clearTimeout(timer)
  }, [projectId, promptRecipe, advancedEnabled, prompt, negativePrompt, modelName, duration, firstFrameId, lastFrameId, referenceAssetIds, selectedTemplateId, generationMode, aspectRatio, resolution, generateAudio, constraintsEnabled, seedLock, seed])

  const fetchAll = () => {
    Promise.all([
      videoGenApi.templates(projectId),
      videoGenApi.referenceImages(projectId),
      videoGenApi.versions(projectId),
    ])
      .then(([t, r, v]) => {
        setTemplates(t.data)
        setRefImages(r.data)
        setVersions(v.data)
      })
      .catch(() => {})
  }

  useEffect(() => {
    fetchAll()
  }, [projectId])

  // 当前新任务只开放 Seedance，避免高级配方在不同视频模型间产生语义漂移。
  useEffect(() => {
    videoGenApi
      .providers(projectId)
      .then((res) => {
        const seedance = (res.data || []).find((p: any) => p.provider === 'seedance')
        const list = seedance ? [seedance] : []
        setProviders(list)
        const def = seedance
        if (def) {
          setSelectedProvider('seedance')
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
    if (p && p.capabilities?.multi_reference_video !== true && generationMode === 'multi_reference_video') {
      setGenerationMode('image_to_video')
      setReferenceAssetIds([])
      message.info(`${PROVIDER_LABELS[p.provider] || p.provider} 不支持多参考图模式，已切换为单图生视频`)
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
        setActiveJob(response.data)
        if (['success', 'failed', 'cancelled'].includes(response.data.status)) {
          clearInterval(timer)
          setActiveJobId(null)
          setSubmitting(false)
          if (response.data.status === 'success') {
            message.success(response.data.asset_status === 'ready' ? '视频生成完成，已写入素材库' : '视频生成完成')
          } else if (response.data.status === 'failed') {
            message.error(response.data.error_message || '视频生成失败，可点击重试')
          }
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
  }, [activeJobId, projectId, message])

  const firstFrame = useMemo(() => refImages.find((i) => i.id === firstFrameId) || null, [refImages, firstFrameId])
  const lastFrame = useMemo(() => refImages.find((i) => i.id === lastFrameId) || null, [refImages, lastFrameId])

  const canFirstLast = providerCaps.first_last_frame_video === true
  const canMultiReference = providerCaps.multi_reference_video === true
  const canImageToVideo = providerCaps.image_to_video !== false

  // 右侧分类：建筑外景运镜（单图图生）/ 首尾帧与多参考图·创意运镜
  const displayTemplates = useMemo(() => {
    const scoped = templates.filter((t) => {
      if (templateScopeFilter === 'personal') return t.scope === 'personal'
      if (templateScopeFilter === 'organization') return t.is_system || t.scope === 'organization'
      return true
    })
    if (generationMode === 'multi_reference_video') {
      return scoped.filter((t) => templateSupportsMode(t, generationMode))
    }
    if (activeTab === 'creative') {
      return scoped.filter((t) => templateSupportsMode(t, 'first_last_frame_video'))
    }
    return scoped.filter((t) => templateSupportsMode(t, 'image_to_video'))
  }, [templates, activeTab, generationMode, templateScopeFilter])

  // 最终提交提示词预览（与后端 build_final_prompt 保持一致）
  const finalPromptPreview = useMemo(() => {
    const constraints = constraintsEnabled ? (templates.find((t) => t.id === selectedTemplateId)?.default_arch_constraints || []) : []
    const parts = [sanitizePromptResolution(expandRecipePrompt(prompt, activePromptRecipe))]
    if (constraints.length) parts.push(constraints.join('；'))
    return parts.filter(Boolean).join('。')
  }, [prompt, activePromptRecipe, constraintsEnabled, selectedTemplateId, templates])

  useEffect(() => {
    if (!projectId || (!prompt.trim() && !activePromptRecipe)) {
      setCompiledPromptPreview('')
      return
    }
    let cancelled = false
    const timer = window.setTimeout(() => {
      videoGenApi.compilePrompt(projectId, {
        positive_prompt: prompt,
        negative_prompt: negativePrompt || null,
        prompt_recipe: activePromptRecipe,
        template_id: selectedTemplateId || null,
        constraints_enabled: constraintsEnabled,
        resolution,
      }).then((response) => {
        if (!cancelled) setCompiledPromptPreview(response.data.provider_prompt || response.data.positive_prompt || '')
      }).catch(() => {
        if (!cancelled) setCompiledPromptPreview('')
      })
    }, 350)
    return () => {
      cancelled = true
      window.clearTimeout(timer)
    }
  }, [projectId, prompt, negativePrompt, activePromptRecipe, selectedTemplateId, constraintsEnabled, resolution])

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
    const tMode = templateMode(t)
    const flexibleTemplate = isFlexibleReferenceTemplate(t)
    const modeToCheck = flexibleTemplate ? generationMode : tMode
    if (modeToCheck === 'first_last_frame_video' && !canFirstLast) {
      message.warning('当前 Provider 不支持首尾帧，请先切换到支持首尾帧的模型')
      return
    }
    if (modeToCheck === 'multi_reference_video' && !canMultiReference) {
      message.warning('当前 Provider 不支持多参考图，请先切换到支持多参考图的模型')
      return
    }
    setSelectedTemplateId(t.id)
    setAdvancedEnabled(false)
    const recipe = t.prompt_recipe || {}
    const recommended = recipe.recommended && typeof recipe.recommended === 'object' ? recipe.recommended : {}
    setPromptRecipe(recipe)
    setPrompt(templatePrompt(t).slice(0, 500))
    setNegativePrompt(String(recipe.negative_prompt || t.default_negative_prompt || ''))
    setDuration(recipeDuration(recommended.duration, t.recommended_duration || 5))
    setAspectRatio(String(recommended.aspect_ratio || t.recommended_aspect_ratio || 'adaptive'))
    setResolution(normalizeResolution(recommended.resolution || t.recommended_resolution, resolution))
    setConstraintsEnabled(true)
    if (!flexibleTemplate && tMode !== generationMode) {
      if (tMode === 'first_last_frame_video' && canFirstLast) {
        setGenerationMode('first_last_frame_video')
      } else if (tMode === 'multi_reference_video' && canMultiReference) {
        setGenerationMode('multi_reference_video')
      } else {
        setGenerationMode('image_to_video')
      }
    }
  }

  const openTemplateApply = (template: VideoGenerationTemplate) => {
    setTemplateToApply(template)
    setApplyFirstFrameId(firstFrameId)
    setApplyLastFrameId(lastFrameId)
    const originalReferences = (template.reference_frame_asset_ids || []).filter((id) =>
      refImages.some((image) => image.id === id),
    )
    setApplyReferenceIds(
      originalReferences.length === templateReferenceCount(template)
        ? originalReferences
        : referenceAssetIds,
    )
    setApplySubject('')
    setApplyScene('')
    setTemplateApplyOpen(true)
  }

  const confirmTemplateApply = () => {
    if (!templateToApply) return
    const flexibleTemplate = isFlexibleReferenceTemplate(templateToApply)
    const mode = flexibleTemplate ? generationMode : templateMode(templateToApply)
    if (mode === 'first_last_frame_video' && !canFirstLast) {
      message.warning('当前 Provider 不支持首尾帧，请先切换到支持首尾帧的模型')
      return
    }
    if (mode === 'multi_reference_video' && !canMultiReference) {
      message.warning('当前 Provider 不支持多参考图，请先切换到支持多参考图的模型')
      return
    }
    if (!applyFirstFrameId) {
      message.warning('请先选择新的建筑首帧')
      return
    }
    if (mode === 'first_last_frame_video' && !applyLastFrameId) {
      message.warning('这个模板需要同时选择新的建筑首帧和尾帧')
      return
    }
    const requiredReferenceCount = templateReferenceCount(templateToApply)
    if (mode === 'multi_reference_video' && applyReferenceIds.length !== requiredReferenceCount) {
      message.warning(`这个模板需要按顺序选择 ${requiredReferenceCount} 张图片`)
      return
    }
    handleSelectTemplate(templateToApply)
    setGenerationMode(mode)
    setFirstFrameId(mode === 'multi_reference_video' ? applyReferenceIds[0] : applyFirstFrameId)
    setLastFrameId(mode === 'first_last_frame_video' ? applyLastFrameId : '')
    setReferenceAssetIds(mode === 'multi_reference_video' ? applyReferenceIds : [])
    const replacements = [
      applySubject.trim() ? `当前建筑主体：${applySubject.trim()}` : '',
      applyScene.trim() ? `场景与环境：${applyScene.trim()}` : '',
    ].filter(Boolean)
    const basePrompt = templatePrompt(templateToApply)
    setPrompt([basePrompt, ...replacements].filter(Boolean).join('。').slice(0, 500))
    setTemplateApplyOpen(false)
    message.success('模板已套用，图片和生成参数已带入')
  }

  const templateApplyMode = templateToApply
    ? (isFlexibleReferenceTemplate(templateToApply) ? generationMode : templateMode(templateToApply))
    : null
  const originalTemplateReferenceIds = (templateToApply?.reference_frame_asset_ids || []).filter((id) =>
    refImages.some((image) => image.id === id),
  )
  const usingOriginalTemplateFrames = Boolean(
    templateToApply
    && originalTemplateReferenceIds.length === templateReferenceCount(templateToApply)
    && applyReferenceIds.length === originalTemplateReferenceIds.length
    && applyReferenceIds.every((id, index) => id === originalTemplateReferenceIds[index]),
  )

  const handleRetryJob = async () => {
    if (!activeJob) return
    setSubmitting(true)
    try {
      const response = await videoGenApi.retryTask(projectId, activeJob.id)
      setActiveJob(response.data)
      setActiveJobId(response.data.id)
      message.info('已重新提交生成任务')
    } catch {
      setSubmitting(false)
    }
  }

  // 提示词大师：读参考帧 + 用户意图，生成视频提示词
  const handlePromptMaster = async () => {
    const firstOk = !!firstFrameId
    const lastOk = generationMode === 'first_last_frame_video' ? !!lastFrameId : true
    const refsOk = generationMode === 'multi_reference_video' ? referenceAssetIds.length >= 2 : true
    if (!firstOk || !lastOk || !refsOk) {
      message.warning(generationMode === 'multi_reference_video' ? '请按顺序选择至少两张参考图' : generationMode === 'first_last_frame_video' ? '请先选择首帧与尾帧图片' : '请先选择一张参考帧图片')
      return
    }
    setMasterLoading(true)
    try {
      const res = await videoGenApi.promptMaster(projectId, {
        first_frame_asset_id: firstFrameId,
        last_frame_asset_id: generationMode === 'first_last_frame_video' ? lastFrameId : undefined,
        reference_asset_ids: generationMode === 'multi_reference_video' ? referenceAssetIds : undefined,
        template_id: selectedTemplateId || undefined,
        intent: prompt.trim() || undefined,
        generation_mode: generationMode,
      })
      const parsed = parsePromptMasterPayload(res.data as Record<string, any>)
      // 高级参数是输出规格的唯一来源，提示词大师返回的“4K/超高清”等
      // 描述不能覆盖当前页面选择的 720p/1080p。
      setPrompt(sanitizePromptResolution(parsed.prompt).slice(0, 500))
      if (parsed.negativePrompt) setNegativePrompt(parsed.negativePrompt)
      setPromptRecipe(parsed.recipe)
      setAdvancedEnabled(false)
      message.success(
        parsed.name
          ? `已生成「${parsed.name}」，镜头提示词和结构化配方已分别归位`
          : res.data.is_mock
          ? '提示词已生成（演示模式）'
          : res.data.vision_used
            ? `提示词已由${res.data.provider === 'kimi' ? 'Kimi 多模态模型' : res.data.provider === 'volcengine_vision' ? '火山方舟视觉模型' : '视觉模型'}生成`
            : '提示词大师已生成',
      )
    } catch {
      // 拦截器已提示
    } finally {
      setMasterLoading(false)
    }
  }

  const handleSubmit = async (structureConflictConfirmed = false) => {
    if (!firstFrameId) {
      message.warning('请先在左侧明确选择一张首帧图片，再发起视频生成')
      return
    }
    if (generationMode === 'first_last_frame_video' && !lastFrameId) {
      message.warning('首尾帧模式必须明确选择两张图片：第一张为首帧，第二张为尾帧')
      return
    }
    if (generationMode === 'multi_reference_video' && referenceAssetIds.length < 2) {
      message.warning('多参考图模式需要按顺序选择至少两张图片')
      return
    }
    if (!prompt.trim() && !activePromptRecipe) {
      message.warning('请填写视频提示词')
      return
    }

    // 建筑约束冲突预检。检测到施工工序类关键词时，先让用户明确确认，
    // 不要求用户为了通过规则而反复改写专业描述。
    if (!structureConflictConfirmed) {
      try {
        const check = await videoGenApi.constraintCheck(projectId, prompt, activePromptRecipe)
        if (check.data.blocked) {
          Modal.confirm({
            title: '检测到可能改变工程结构的描述',
            icon: <SafetyOutlined />,
            content: (
              <div>
                <p style={{ marginBottom: 8 }}>
                  系统识别到：{check.data.conflicts.join('、')}。
                </p>
                <p style={{ marginBottom: 0, color: '#667085' }}>
                  如果这里描述的是临时支撑、模板或施工工序，而不是修改整栋建筑，可以确认继续。本次确认只对当前生成任务生效。
                </p>
              </div>
            ),
            okText: '确认继续生成',
            cancelText: '返回修改',
            okButtonProps: { danger: true },
            onOk: () => handleSubmit(true),
          })
          return
        }
      } catch {
        // 后端也会拦截
      }
    }

    setSubmitting(true)
    try {
      const effectivePrompt = sanitizePromptResolution(prompt)
      const res = await videoGenApi.createTask(projectId, {
        generation_mode: generationMode,
        first_frame_asset_id: firstFrameId,
        last_frame_asset_id: generationMode === 'first_last_frame_video' ? lastFrameId : undefined,
        reference_asset_ids: generationMode === 'multi_reference_video' ? referenceAssetIds : [],
        template_id: selectedTemplateId || null,
        prompt_recipe: activePromptRecipe || undefined,
        provider: 'seedance',
        model_name: modelName || undefined,
        positive_prompt: effectivePrompt,
        negative_prompt: negativePrompt || null,
        duration,
        aspect_ratio: aspectRatio,
        resolution,
        seed: seedLock ? seed : null,
        generate_audio: generateAudio,
        constraints_enabled: constraintsEnabled,
        structure_conflict_confirmed: structureConflictConfirmed,
        idempotency_key: `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
      })
      setActiveJob(res.data)
      setActiveJobId(res.data.id)
      message.success('视频生成任务已提交')
      setTimeout(fetchAll, 1500)
    } catch {
      setSubmitting(false)
      // 拦截器已提示
    }
  }

  const openAdvancedWorkbench = () => {
    const advancedState = {
      advancedWorkbench: true,
      recipe: promptRecipe,
      advancedEnabled: false,
      prompt,
      negativePrompt,
      selectedProvider,
      modelName,
      duration,
      firstFrameId,
      lastFrameId,
      referenceAssetIds,
      selectedTemplateId,
      generationMode,
      aspectRatio,
      resolution,
      generateAudio,
      constraintsEnabled,
      seedLock,
      seed,
    }
    // 用户可能刚选完首尾帧就进入高级页；立即保存，不能依赖防抖定时器。
    saveAiVideoDraft(projectId, {
      recipe: promptRecipe,
      advancedEnabled: false,
      prompt,
      negativePrompt,
      selectedProvider: 'seedance',
      modelName,
      duration,
      firstFrameId,
      lastFrameId,
      referenceAssetIds,
      selectedTemplateId,
      generationMode,
      aspectRatio,
      resolution,
      generateAudio,
      constraintsEnabled,
      seedLock,
      seed,
    })
    navigate(`/project/${projectId}/ai-video/advanced`, { state: advancedState })
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

  const handleDeleteVersion = async (v: VideoGenerationVersion) => {
    try {
      await videoGenApi.deleteVersion(projectId, v.id)
      message.success('版本已删除')
      fetchAll()
    } catch {
      // 拦截器已提示
    }
  }

  const handleDeleteTemplate = async (template: VideoGenerationTemplate) => {
    if (template.is_system || deletingTemplateId) return
    setDeletingTemplateId(template.id)
    try {
      await videoGenApi.deleteTemplate(projectId, template.id)
      if (selectedTemplateId === template.id) {
        setSelectedTemplateId('')
        setPromptRecipe(null)
      }
      if (templateToApply?.id === template.id) {
        setTemplateToApply(null)
        setTemplateApplyOpen(false)
      }
      message.success('模板已删除')
      fetchAll()
    } catch {
      // 拦截器已提示
    } finally {
      setDeletingTemplateId(null)
    }
  }

  const openRenameVersion = (v: VideoGenerationVersion) => {
    setRenameVersionTarget(v)
    setRenameVersionValue(versionDisplayName(v))
  }

  const handleRenameVersion = async () => {
    if (!renameVersionTarget) return
    const name = renameVersionValue.trim()
    if (!name) {
      message.warning('请输入视频版本名称')
      return
    }
    setRenamingVersion(true)
    try {
      await videoGenApi.renameVersion(projectId, renameVersionTarget.id, name)
      message.success('视频版本已重命名')
      setRenameVersionTarget(null)
      fetchAll()
    } catch {
      // 拦截器已提示
    } finally {
      setRenamingVersion(false)
    }
  }

  return (
    <div className="ai-video-page">
      {/* ============ 左侧：生成控制面板 ============ */}
      <div className="ai-video-controls">
        <div style={{ flex: 1, overflowY: 'auto', padding: 16 }}>
          {/* 1. 功能标签 */}
          <Text strong style={{ fontSize: 14 }}>生成功能</Text>
          <Segmented
            block
            style={{ marginTop: 8 }}
            value={generationMode}
            onChange={(v) => {
              const next = String(v) as 'image_to_video' | 'first_last_frame_video' | 'multi_reference_video'
              setGenerationMode(next)
              if (next === 'multi_reference_video' && firstFrameId && !referenceAssetIds.includes(firstFrameId)) {
                setReferenceAssetIds([firstFrameId])
              }
            }}
            options={[
              { label: '首尾帧视频', value: 'first_last_frame_video', disabled: !canFirstLast },
              { label: '单图生视频', value: 'image_to_video', disabled: !canImageToVideo },
              { label: '多参考图（Seedance 2.0）', value: 'multi_reference_video', disabled: !canMultiReference },
            ]}
          />
          {generationMode === 'first_last_frame_video' && !canFirstLast && (
            <Text type="warning" style={{ display: 'block', marginTop: 8, fontSize: 12 }}>
              当前模型不支持首尾帧，且不允许降级为普通图生视频
            </Text>
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
            ) : generationMode === 'multi_reference_video' ? (
              <div>
                <Select
                  mode="multiple"
                  maxCount={9}
                  value={referenceAssetIds}
                  onChange={(ids) => {
                    setReferenceAssetIds(ids)
                    setFirstFrameId(ids[0] || '')
                  }}
                  placeholder="按镜头参考顺序选择 2~9 张图片"
                  style={{ width: '100%' }}
                  options={refImages.map((img) => ({ label: img.name, value: img.id }))}
                  optionRender={(option) => {
                    const image = refImages.find((item) => item.id === option.value)
                    return <Space><img src={image?.url} alt="" style={{ width: 32, height: 24, objectFit: 'cover', borderRadius: 3 }} /><span>{option.label}</span></Space>
                  }}
                />
                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, minmax(0, 1fr))', gap: 8, marginTop: 10 }}>
                  {referenceAssetIds.map((id, index) => {
                    const image = refImages.find((item) => item.id === id)
                    return image ? <div key={id} style={{ minWidth: 0 }}><div style={{ position: 'relative', height: 82, borderRadius: 7, overflow: 'hidden', background: '#eef2f7' }}><img src={image.url} alt={image.name} style={{ width: '100%', height: '100%', objectFit: 'contain' }} /><Tag color={index === 0 ? 'blue' : 'default'} style={{ position: 'absolute', left: 4, top: 4, margin: 0 }}>{index + 1}</Tag></div><Text ellipsis={{ tooltip: image.name }} style={{ display: 'block', fontSize: 11, marginTop: 3 }}>{image.name}</Text></div> : null
                  })}
                </div>
                <Text type="secondary" style={{ display: 'block', marginTop: 6, fontSize: 11 }}>第一张作为首参考图，其余图片按选中顺序发送给 Seedance。</Text>
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
                  {p.is_mock ? '（本地演示）' : !p.available ? '（未配置）' : ''}
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
            <div><Text strong style={{ fontSize: 12, color: '#334155' }}>模型：</Text>{modelName || '无'}</div>
            <div>图生视频：{canImageToVideo ? '支持' : '不支持'}</div>
            <div>首尾帧过渡：{canFirstLast ? '支持' : '不支持'}</div>
            <div>多参考图：{canMultiReference ? '支持（2~9张）' : '不支持'}</div>
            <div>生成声音：{providerCaps.generate_audio === true ? '支持（可关闭）' : '不支持'}</div>
            <div>视频时长：5 / 8 / 10 / 15 秒</div>
          </div>

          <div style={{ marginTop: 12, padding: 12, border: '1px solid #b9cceb', borderRadius: 8, background: 'linear-gradient(135deg, #f4f8ff 0%, #ffffff 72%)' }}>
            <Space align="start" style={{ width: '100%', justifyContent: 'space-between' }}>
              <Space align="start" size={9}>
                <SafetyOutlined style={{ marginTop: 3, color: '#2457A6', fontSize: 16 }} />
                <div>
                  <Text strong style={{ display: 'block', color: '#183b73', fontSize: 13 }}>高级生成 · 施工提示词工程</Text>
                  <Text type="secondary" style={{ display: 'block', marginTop: 3, fontSize: 11, lineHeight: 1.45 }}>WBS、施工状态、双时间轴和验收清单集中配置，统一投喂 Seedance。</Text>
                  <Text type={advancedEnabled ? 'success' : 'secondary'} style={{ display: 'block', marginTop: 4, fontSize: 11, lineHeight: 1.45 }}>
                    {advancedEnabled
                      ? '高级配方已应用到本次生成。'
                      : isConstructionRecipe(promptRecipe)
                        ? '提示词大师已解析施工配方；请进入工作台查看分栏字段，未应用前不会投喂。'
                        : '未进入并应用工作台时，快速生成只使用普通镜头提示词。'}
                  </Text>
                </div>
              </Space>
              <Button
                type="primary"
                size="small"
                onClick={openAdvancedWorkbench}
              >进入工作台</Button>
            </Space>
          </div>

          {/* 5. 输入描述 */}
          <Divider style={{ margin: '14px 0' }} />
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline' }}>
            <div><Text strong style={{ fontSize: 14 }}>镜头提示词</Text><Text type="secondary" style={{ display: 'block', fontSize: 11, marginTop: 3 }}>描述镜头运动、建筑状态和画面节奏，最多 500 个字符。</Text></div>
            <Text type={prompt.length >= 500 ? 'danger' : 'secondary'} style={{ fontSize: 11 }}>{prompt.length} / 500</Text>
          </div>
          <div style={{ marginTop: 9 }}>
            <Input.TextArea
              rows={6}
              value={prompt}
              onChange={(e) => setPrompt(e.target.value.slice(0, 500))}
              placeholder="描述你想要的镜头与画面，例如：镜头缓慢推进，建筑主体稳定居中，光影自然"
              style={{ fontSize: 13, resize: 'vertical' }}
              maxLength={500}
            />
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginTop: 8 }}>
              <Text type="secondary" style={{ fontSize: 11 }}>AI读取多图生成提示词。</Text>
              <Button type="primary" icon={<ThunderboltOutlined />} loading={masterLoading} onClick={handlePromptMaster}>提示词大师</Button>
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
                            background: '#F8FAFC',
                            border: '1px solid #E4E9F0',
                            borderRadius: 6,
                            fontSize: 12,
                            color: '#444',
                            minHeight: 40,
                            whiteSpace: 'pre-wrap',
                          }}
                        >
                          {compiledPromptPreview || finalPromptPreview || '（空）'}
                        </div>
                      </div>

                    </div>
                  ),
                },
              ]}
            />
          </div>
        </div>

        {activeJob && (
          <Card size="small" style={{ margin: '12px 16px', borderColor: activeJob.status === 'failed' ? '#ffccc7' : '#d6e4ff' }}>
            <Space style={{ width: '100%', justifyContent: 'space-between' }} align="start">
              <div>
                <Text strong style={{ fontSize: 13 }}>
                  {activeJob.status === 'success' ? '生成完成' : activeJob.status === 'failed' ? '生成失败' : '视频生成中'}
                </Text>
                <Text type="secondary" style={{ display: 'block', fontSize: 11, marginTop: 3 }}>
                  {PROVIDER_LABELS[activeJob.provider] || activeJob.provider} · {activeJob.model_name || '默认模型'} · {activeJob.duration}s
                </Text>
              </div>
              {activeJob.status === 'success' && <Tag color="green" icon={<CheckCircleOutlined />}>已入素材库</Tag>}
              {activeJob.status === 'failed' && <Button size="small" icon={<ReloadOutlined />} onClick={handleRetryJob}>重试</Button>}
            </Space>
            {['queued', 'running'].includes(activeJob.status) && <Progress percent={activeJob.progress || 5} status="active" size="small" style={{ marginTop: 8, marginBottom: 0 }} />}
            {activeJob.status === 'failed' && <Text type="danger" style={{ display: 'block', fontSize: 11, marginTop: 8 }}>{activeJob.error_message || 'Provider 返回失败，请检查配置后重试'}</Text>}
            {activeJob.status === 'success' && <Text type="secondary" style={{ display: 'block', fontSize: 11, marginTop: 8 }}>结果素材 ID：{activeJob.result_asset_id || '等待素材索引'}</Text>}
            {activeJob.quality_report?.engineering_review && (
              <Alert
                type="warning"
                showIcon
                message="工程质检需人工复核"
                description={activeJob.quality_report.engineering_review.note || '请对照图纸、施工方案和目标状态确认构件位置、工序连续性及安全防护。'}
                style={{ marginTop: 8, fontSize: 11 }}
              />
            )}
          </Card>
        )}

        {/* 7. 底部主操作按钮 */}
        <div className="ai-video-submit-bar">
          <Button
            block
            loading={submitting}
            onClick={() => void handleSubmit()}
            icon={<PlayCircleOutlined />}
            className="ai-video-submit"
          >
            开始生成视频
          </Button>
        </div>
      </div>

      {/* ============ 右侧：视频模板素材库 ============ */}
      <div className="ai-video-library">
        {/* 1. 标题区 */}
        <div className="page-header" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-end' }}>
          <div>
            <Title level={4} style={{ marginBottom: 2 }}>
              专业视频渲染引擎
            </Title>
            <Text type="secondary" style={{ fontSize: 13 }}>
              选择模板一键套用，或自定义提示词生成投标演示视频
            </Text>
          </div>
          <Tag color="geekblue" style={{ fontSize: 11, marginBottom: 4 }}>
            图生视频 · 首尾帧
          </Tag>
          <Button size="small" icon={<SafetyOutlined />} onClick={openAdvancedWorkbench} style={{ marginLeft: 8 }}>
            施工配方制作
          </Button>
          <Button size="small" onClick={() => setDrawerOpen(true)} style={{ marginLeft: 8 }}>
            版本中心
          </Button>
          <Button size="small" type="primary" icon={<UploadOutlined />} onClick={() => navigate(`/project/${projectId}/ai-video/templates/new`)} style={{ marginLeft: 8 }}>
            从视频创建模板
          </Button>
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
                  首尾帧 / 多参考图·创意运镜
                  <Tag color="volcano" style={{ fontSize: 10, lineHeight: '16px', marginInlineStart: 6 }}>
                    NEW
                  </Tag>
                </span>
              ),
            },
          ]}
        />

        <Space style={{ marginBottom: 12 }} wrap>
          <Text type="secondary" style={{ fontSize: 12 }}>模板范围</Text>
          <Segmented
            size="small"
            value={templateScopeFilter}
            onChange={(value) => setTemplateScopeFilter(value as 'all' | 'personal' | 'organization')}
            options={[
              { label: '全部可用', value: 'all' },
              { label: '我的模板', value: 'personal' },
              { label: '企业模板', value: 'organization' },
            ]}
          />
        </Space>

        {/* 3. 模板瀑布 / 网格 */}
        {displayTemplates.length === 0 && <Empty description="当前分类暂无模板" style={{ marginTop: 40 }} />}
        <Row gutter={[16, 16]}>
          {displayTemplates.map((t) => {
            const preview = TEMPLATE_PREVIEWS[t.name] || {}
            const isFL = (t.applicable_modes || []).includes('first_last_frame_video')
            const isMulti = (t.applicable_modes || []).includes('multi_reference_video') || (generationMode === 'multi_reference_video' && (t.applicable_modes || []).includes('image_to_video'))
            const selected = selectedTemplateId === t.id
            const backendPreview = {
              video: templateAssetUrl(t.preview_file_key) || preview.video,
              first: templateAssetUrl(t.first_frame_file_key || t.cover_file_key) || preview.first,
              last: templateAssetUrl(t.last_frame_file_key) || preview.last,
            }
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
                    border: selected ? '1.5px solid #2457A6' : '1px solid #E4E9F0',
                    boxShadow: selected ? '0 4px 16px rgba(36, 87, 166, 0.14)' : undefined,
                  }}
                  cover={<TemplatePreview t={t} preview={backendPreview} isFL={isFL} />}
                >
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: 8, flexShrink: 0 }}>
                    <Text strong style={{ fontSize: 14, flex: 1, minWidth: 0 }} ellipsis={{ tooltip: t.name }}>{t.name}</Text>
                    {isFL && <Tag color="purple" style={{ fontSize: 10, marginInlineEnd: 0, flexShrink: 0 }}>首尾帧</Tag>}
                    {isMulti && <Tag color="cyan" style={{ fontSize: 10, marginInlineEnd: 0, flexShrink: 0 }}>多参考图</Tag>}
                  </div>
                  <Paragraph
                    type="secondary"
                    style={{ fontSize: 12, marginTop: 6, marginBottom: 0, lineHeight: '20px', minHeight: 40, flex: 1 }}
                    ellipsis={{ rows: 2, tooltip: t.description }}
                  >
                    {t.description}
                  </Paragraph>
                  <div style={{ marginTop: 8, flexShrink: 0 }}>
                    {(t.category || t.prompt_recipe?.category) && <Tag color="blue" style={{ fontSize: 11 }}>{t.category || t.prompt_recipe?.category}</Tag>}
                    {t.recommended_camera_motion && (
                      <Tag style={{ fontSize: 11, color: '#475569' }}>{t.recommended_camera_motion}</Tag>
                    )}
                    <Tag style={{ fontSize: 11, color: '#475569' }}>{t.recommended_duration}s</Tag>
                    <Tag color={t.is_system || t.scope === 'organization' ? 'blue' : 'gold'} style={{ fontSize: 11 }}>
                      {t.is_system ? '系统模板' : t.scope === 'personal' ? '个人模板' : '企业模板'}
                    </Tag>
                  </div>
                  <div style={{ minHeight: 26, marginTop: 4 }}>
                    {(t.tags || []).slice(0, 3).map((tag) => <Tag key={tag} style={{ fontSize: 10, marginBottom: 4 }}>{tag}</Tag>)}
                  </div>
                  <Button
                    type={selected ? 'primary' : 'default'}
                    size="small"
                    block
                    icon={<ThunderboltOutlined />}
                    onClick={(event) => {
                      event.stopPropagation()
                      openTemplateApply(t)
                    }}
                    style={{ marginTop: 8 }}
                  >
                    使用此模板
                  </Button>
                  {!t.is_system && (
                    <Popconfirm
                      title="删除这个模板？"
                      description="删除后模板将从模板库移除，已生成的视频和历史任务不会受影响。"
                      okText="删除"
                      cancelText="取消"
                      okButtonProps={{ danger: true }}
                      onConfirm={() => void handleDeleteTemplate(t)}
                    >
                      <Button
                        type="link"
                        danger
                        size="small"
                        block
                        icon={<DeleteOutlined />}
                        loading={deletingTemplateId === t.id}
                        onClick={(event) => event.stopPropagation()}
                        style={{ marginTop: 4 }}
                      >
                        删除模板
                      </Button>
                    </Popconfirm>
                  )}
                </Card>
              </Col>
            )
          })}
        </Row>
      </div>

      <Modal
        title={templateToApply ? `套用模板：${templateToApply.name}` : '套用模板'}
        open={templateApplyOpen}
        onCancel={() => setTemplateApplyOpen(false)}
        onOk={confirmTemplateApply}
        okText="套用模板"
        width={680}
      >
        {templateToApply && (
          <div>
            <Text type="secondary" style={{ display: 'block', marginBottom: 14 }}>
              多图施工模板的关键帧顺序就是动作本体。可直接使用样片关键帧复刻节奏，也可以替换为当前项目同阶段图片。
            </Text>
            {templateApplyMode === 'multi_reference_video' && (
              <Alert
                type={usingOriginalTemplateFrames ? 'success' : 'warning'}
                showIcon
                style={{ marginBottom: 14 }}
                message={usingOriginalTemplateFrames ? '已带入样片原始施工关键帧（推荐）' : '当前正在使用替换图片'}
                description={usingOriginalTemplateFrames
                  ? `Seedance 将按 ${originalTemplateReferenceIds.length} 张关键帧的顺序理解施工节奏。`
                  : '替换图片必须逐张对应模板中的施工阶段；只放首尾两张会退化为 AI 自由补间。'}
                action={originalTemplateReferenceIds.length === templateReferenceCount(templateToApply)
                  ? <Button size="small" onClick={() => setApplyReferenceIds(originalTemplateReferenceIds)}>恢复样片关键帧</Button>
                  : undefined}
              />
            )}
            <Row gutter={14}>
              {templateApplyMode === 'multi_reference_video' ? (
                <Col span={24}>
                  <Text strong style={{ fontSize: 12 }}>施工关键帧（按实际发生顺序）</Text>
                  <Select
                    mode="multiple"
                    maxCount={templateReferenceCount(templateToApply)}
                    showSearch
                    optionFilterProp="label"
                    value={applyReferenceIds}
                    placeholder={`按施工顺序选择 ${templateReferenceCount(templateToApply)} 张关键帧`}
                    style={{ width: '100%', marginTop: 6 }}
                    onChange={setApplyReferenceIds}
                    options={refImages.map((image) => ({ label: image.name, value: image.id, image }))}
                    optionRender={(option) => {
                      const image = (option.data as { image?: ReferenceImage }).image
                      return <Space><img src={image?.url} alt="" style={{ width: 44, height: 32, objectFit: 'cover', borderRadius: 4 }} /><span>{option.label}</span></Space>
                    }}
                  />
                </Col>
              ) : <Col span={templateApplyMode === 'first_last_frame_video' ? 12 : 24}>
                <Text strong style={{ fontSize: 12 }}>新的建筑首帧</Text>
                <Select
                  showSearch
                  optionFilterProp="label"
                  value={applyFirstFrameId || undefined}
                  placeholder="选择素材库中的首帧图片"
                  style={{ width: '100%', marginTop: 6 }}
                  onChange={setApplyFirstFrameId}
                  options={refImages.map((image) => ({ label: image.name, value: image.id, image }))}
                  optionRender={(option) => {
                    const image = (option.data as { image?: ReferenceImage }).image
                    return <Space><img src={image?.url} alt="" style={{ width: 44, height: 32, objectFit: 'cover', borderRadius: 4 }} /><span>{option.label}</span></Space>
                  }}
                />
              </Col>}
              {templateApplyMode === 'first_last_frame_video' && (
                <Col span={12}>
                  <Text strong style={{ fontSize: 12 }}>新的建筑尾帧</Text>
                  <Select
                    showSearch
                    optionFilterProp="label"
                    value={applyLastFrameId || undefined}
                    placeholder="选择素材库中的尾帧图片"
                    style={{ width: '100%', marginTop: 6 }}
                    onChange={setApplyLastFrameId}
                    options={refImages.map((image) => ({ label: image.name, value: image.id, image }))}
                    optionRender={(option) => {
                      const image = (option.data as { image?: ReferenceImage }).image
                      return <Space><img src={image?.url} alt="" style={{ width: 44, height: 32, objectFit: 'cover', borderRadius: 4 }} /><span>{option.label}</span></Space>
                    }}
                  />
                </Col>
              )}
            </Row>
            <Divider style={{ margin: '18px 0 12px' }} />
            <Row gutter={14}>
              <Col span={12}>
                <Text strong style={{ fontSize: 12 }}>建筑主体描述（可选）</Text>
                <Input.TextArea
                  rows={3}
                  value={applySubject}
                  onChange={(event) => setApplySubject(event.target.value)}
                  placeholder="例如：当前项目的白色幕墙办公楼"
                  style={{ marginTop: 6 }}
                />
              </Col>
              <Col span={12}>
                <Text strong style={{ fontSize: 12 }}>场景与环境描述（可选）</Text>
                <Input.TextArea
                  rows={3}
                  value={applyScene}
                  onChange={(event) => setApplyScene(event.target.value)}
                  placeholder="例如：阴天，前景保留施工道路和绿化"
                  style={{ marginTop: 6 }}
                />
              </Col>
            </Row>
            <Alert
              type="info"
              showIcon
              style={{ marginTop: 16 }}
              message={`将自动带入：${templateToApply.recommended_duration}s · ${templateToApply.recommended_aspect_ratio} · ${templateToApply.recommended_resolution}`}
              description="套用后仍可以在左侧编辑提示词和高级参数，再提交真实 Provider 生成。"
            />
          </div>
        )}
      </Modal>

      {/* ============ 生成任务与结果（抽屉） ============ */}
      <Drawer
        title="视频结果版本"
        placement="right"
        width={440}
        open={drawerOpen}
        onClose={() => setDrawerOpen(false)}
      >
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
                <Text strong style={{ fontSize: 12 }} ellipsis={{ tooltip: versionDisplayName(v) }}>
                  {versionDisplayName(v)}
                </Text>
                <Text type="secondary" style={{ fontSize: 10 }}>
                  V{v.version_number} · seed:{v.seed ?? '-'} · {PROVIDER_LABELS[v.provider] || v.provider}
                </Text>
              </Space>
              {v.quality_report?.warnings?.length ? <Tag color="orange" style={{ marginTop: 4 }}>质检：{v.quality_report.warnings[0]}</Tag> : <Tag color="green" style={{ marginTop: 4 }}>质检通过</Tag>}
              <Space style={{ marginTop: 6 }} wrap>
                {v.result_url && (
                  <Button size="small" icon={<DownloadOutlined />} onClick={() => downloadAiVideo(v.result_url!, versionDownloadName(v))}>
                    下载
                  </Button>
                )}
                <Button size="small" icon={<EditOutlined />} onClick={() => openRenameVersion(v)}>
                  重命名
                </Button>
                <Button
                  size="small"
                  type={v.is_selected ? 'default' : 'primary'}
                  icon={<CheckOutlined />}
                  onClick={() => handleSelectVersion(v)}
                >
                  设为当前
                </Button>
                <Button size="small" danger icon={<DeleteOutlined />} onClick={() => handleDeleteVersion(v)}>
                  删除
                </Button>
              </Space>
            </Card>
          ))}
        </div>
      </Drawer>

      {/* 重命名视频版本弹窗 */}
      <Modal
        title="重命名视频版本"
        open={!!renameVersionTarget}
        onCancel={() => setRenameVersionTarget(null)}
        onOk={handleRenameVersion}
        okText="保存"
        confirmLoading={renamingVersion}
      >
        <Input
          autoFocus
          value={renameVersionValue}
          maxLength={255}
          showCount
          placeholder="请输入视频版本名称"
          onChange={(e) => setRenameVersionValue(e.target.value)}
          onPressEnter={handleRenameVersion}
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
  const [previewOpen, setPreviewOpen] = useState(false)
  return (
    <div style={{ flex: 1, minWidth: 0 }}>
      <Text strong style={{ fontSize: 12, color: '#475569' }}>{label}</Text>
      <div
        style={{
          marginTop: 6,
          position: 'relative',
          height: 178,
          borderRadius: 8,
          border: '1px dashed #d9d9d9',
          overflow: 'hidden',
          background: '#F8FAFC',
        }}
      >
        {frame ? (
          <>
            <button type="button" onClick={() => setPreviewOpen(true)} style={{ width: '100%', height: '100%', padding: 0, border: 0, background: '#eef2f7', cursor: 'zoom-in' }}>
              <img src={frame.url} alt={frame.name} style={{ width: '100%', height: '100%', objectFit: 'contain', display: 'block' }} />
            </button>
            <Button aria-label={`清除${label}`} size="small" icon={<ClearOutlined />} style={{ position: 'absolute', top: 6, right: 6 }} onClick={onClear} />
          </>
        ) : (
          <div style={{ width: '100%', height: '100%', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
            <Text type="secondary" style={{ fontSize: 12 }}>未选择{label}</Text>
          </div>
        )}
      </div>
      {frame && <div style={{ marginTop: 6, minHeight: 36 }}>
        <Text strong ellipsis={{ tooltip: frame.name }} style={{ display: 'block', fontSize: 12 }}>{frame.name}</Text>
        <Text type="secondary" style={{ fontSize: 11 }}>
          {formatImageDimensions(frame.width, frame.height) && `${formatImageDimensions(frame.width, frame.height)} · `}
          {frame.source || '素材库'}
        </Text>
      </div>}
      <Space style={{ marginTop: 6, width: '100%' }}>
        <Select
          aria-label={`${label}素材选择`}
          size="small"
          style={{ flex: 1, minWidth: 0 }}
          placeholder="选择素材"
          value={frame?.id}
          onChange={onSelect}
          showSearch
          optionFilterProp="label"
          dropdownMatchSelectWidth={false}
          dropdownStyle={{ minWidth: 320 }}
          options={images.map((i) => ({ value: i.id, label: i.name, image: i }))}
          optionRender={(option) => {
            const image = (option.data as { image?: ReferenceImage }).image
            const dimensions = formatImageDimensions(image?.width, image?.height)
            return <Space style={{ width: '100%' }}><img src={image?.url} alt="" style={{ width: 52, height: 38, objectFit: 'contain', background: '#eef2f7', borderRadius: 4 }} /><span style={{ minWidth: 0 }}><Text ellipsis={{ tooltip: option.label as string }} style={{ display: 'block', maxWidth: 220 }}>{option.label}</Text>{dimensions && <Text type="secondary" style={{ fontSize: 11 }}>{dimensions}</Text>}</span></Space>
          }}
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
      <Modal open={previewOpen} title={frame?.name || label} footer={null} onCancel={() => setPreviewOpen(false)} width={760} centered>
        {frame && <img src={frame.url} alt={frame.name} style={{ width: '100%', maxHeight: '70vh', objectFit: 'contain', background: '#f3f5f8' }} />}
      </Modal>
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
        background: '#F0F4FA',
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
