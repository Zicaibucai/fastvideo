import { useEffect, useMemo, useRef, useState } from 'react'
import {
  Alert,
  App,
  Button,
  Card,
  Col,
  Descriptions,
  Divider,
  Empty,
  Input,
  InputNumber,
  Modal,
  Progress,
  Radio,
  Row,
  Select,
  Slider,
  Space,
  Spin,
  Tag,
  Tooltip,
  Typography,
  Upload,
} from 'antd'
import {
  ArrowLeftOutlined,
  CheckCircleOutlined,
  CloudUploadOutlined,
  DeleteOutlined,
  EyeOutlined,
  VideoCameraOutlined,
  PictureOutlined,
  PlusOutlined,
  RobotOutlined,
  SafetyOutlined,
  ScissorOutlined,
  ThunderboltOutlined,
  UploadOutlined,
} from '@ant-design/icons'
import { useNavigate, useParams } from 'react-router-dom'
import { assetApi, videoGenApi } from '../api'
import { withAuthToken } from '../api/client'
import type { Asset, VideoGenerationJob, VideoTemplateDraft } from '../api/types'
import ConstructionRecipeEditor from '../components/ConstructionRecipeEditor'

const { Title, Text, Paragraph } = Typography
const { Dragger } = Upload

const STEPS = [
  { title: '上传样片', description: '选择专业视频', icon: <CloudUploadOutlined /> },
  { title: '截取镜头', description: '保留一个连续镜头', icon: <ScissorOutlined /> },
  { title: '确认关键帧', description: '首帧、帧序列、尾帧', icon: <PictureOutlined /> },
  { title: 'AI 提炼', description: '生成可复用配方', icon: <RobotOutlined /> },
  { title: '模板提示词', description: '编辑 AI 配方', icon: <RobotOutlined /> },
  { title: '试生成并发布', description: '验证模板效果', icon: <ThunderboltOutlined /> },
]

type TemplateGenerationMode = 'image_to_video' | 'first_last_frame_video' | 'multi_reference_video'
const MAX_REFERENCE_IMAGES = 9

const TEMPLATE_MODE_LABELS: Record<TemplateGenerationMode, string> = {
  image_to_video: '单图生成',
  first_last_frame_video: '首尾帧生成',
  multi_reference_video: '多图生成',
}

const fileUrl = (key?: string) => {
  if (!key) return ''
  return withAuthToken(key.startsWith('/') || /^https?:\/\//i.test(key) ? key : `/files/${key}`)
}

const templateDraftStorageKey = (projectId: string) => `fastvideo:template-draft:${projectId}`

const recipeText = (recipe: Record<string, any> | undefined, key: string, fallback = '') => {
  const value = recipe?.[key]
  if (typeof value !== 'string') return fallback
  if (key === 'prompt' && value.trim().startsWith('{')) {
    try {
      const parsed = JSON.parse(value)
      if (parsed && typeof parsed.prompt === 'string') return parsed.prompt
    } catch {
      // 兼容旧版本已经保存的普通文本提示词。
    }
  }
  return value
}

const recipeItems = (value: any, fallback: string[] = []) => {
  if (Array.isArray(value)) return value.map((item) => String(item).trim()).filter(Boolean)
  if (typeof value === 'string' && value.trim()) {
    return value.split(/[；;、,，\n]+/).map((item) => item.trim()).filter(Boolean)
  }
  return fallback
}

const recipeTimeline = (value: any) => {
  if (Array.isArray(value)) {
    const rows = value
      .filter((item) => item && typeof item === 'object')
      .map((item) => ({
        from: Math.max(0, Math.min(100, Number(item.from ?? item.start ?? 0))),
        to: Math.max(0, Math.min(100, Number(item.to ?? item.end ?? 100))),
        instruction: String(item.instruction || item.description || item.prompt || '').trim(),
      }))
      .filter((item) => item.instruction)
    if (rows.length) return rows
  }
  if (typeof value === 'string' && value.trim()) {
    return [
      { from: 0, to: 20, instruction: '建立首帧构图，锁定建筑主体与空间关系' },
      { from: 20, to: 80, instruction: value.trim() },
      { from: 80, to: 100, instruction: '平稳过渡至尾帧并减速定格，保持结构连续' },
    ]
  }
  return [
    { from: 0, to: 20, instruction: '建立首帧构图，镜头开始缓慢移动' },
    { from: 20, to: 80, instruction: '保持建筑主体稳定，呈现自然空间变化' },
    { from: 80, to: 100, instruction: '平稳到达尾帧构图并减速定格' },
  ]
}

const recipeCamera = (value: any) => {
  if (value && typeof value === 'object') return value
  return { type: String(value || '稳定运镜'), speed: '平稳', direction: '-', path: '-', intensity: '低' }
}

export default function VideoTemplateCreator() {
  const { projectId = '' } = useParams()
  const navigate = useNavigate()
  const { message } = App.useApp()
  const videoRef = useRef<HTMLVideoElement>(null)
  const activeDraftIdRef = useRef<string | null>(null)
  const restoreStartedRef = useRef(false)

  const [draft, setDraft] = useState<VideoTemplateDraft | null>(null)
  const [sourceAsset, setSourceAsset] = useState<Asset | null>(null)
  const [step, setStep] = useState(0)
  const [maxStep, setMaxStep] = useState(0)
  const [uploading, setUploading] = useState(false)
  const [processing, setProcessing] = useState(false)
  const [publishing, setPublishing] = useState(false)
  const [templateName, setTemplateName] = useState('')
  const [description, setDescription] = useState('')
  const [intent, setIntent] = useState('用于建筑外景总体展示，强调体量、立面和场地关系。')
  const [clipStart, setClipStart] = useState(0)
  const [clipEnd, setClipEnd] = useState(5)
  const [middleSeconds, setMiddleSeconds] = useState(2.5)
  const [referenceFrameTimes, setReferenceFrameTimes] = useState<number[]>([])
  const [referenceMode, setReferenceMode] = useState<TemplateGenerationMode>('image_to_video')
  const [referenceFrameLoading, setReferenceFrameLoading] = useState(false)
  const [previewTime, setPreviewTime] = useState(0)
  const [previewMarker, setPreviewMarker] = useState('当前时间')
  const [recipe, setRecipe] = useState<Record<string, any>>({})
  const [previewJob, setPreviewJob] = useState<VideoGenerationJob | null>(null)
  const [previewRequested, setPreviewRequested] = useState(false)
  const [publishScope, setPublishScope] = useState<'personal' | 'organization'>('organization')
  const [providers, setProviders] = useState<any[]>([])
  const [previewProvider, setPreviewProvider] = useState('')
  const [previewModel, setPreviewModel] = useState('')
  const [videoAssets, setVideoAssets] = useState<Asset[]>([])
  const [libraryOpen, setLibraryOpen] = useState(false)
  const [libraryLoading, setLibraryLoading] = useState(false)
  const [selectingLibrary, setSelectingLibrary] = useState(false)
  const [selectingAssetId, setSelectingAssetId] = useState<string | null>(null)

  const sourceVideoUrl = useMemo(() => fileUrl(draft?.source_video_file_key || sourceAsset?.file_key), [draft, sourceAsset])
  const previewUrl = useMemo(() => fileUrl(draft?.preview_file_key || previewJob?.result_url), [draft, previewJob])
  const firstFrameUrl = useMemo(() => fileUrl(draft?.first_frame_file_key), [draft])
  const middleFrameUrl = useMemo(() => fileUrl(draft?.middle_frame_file_key), [draft])
  const lastFrameUrl = useMemo(() => fileUrl(draft?.last_frame_file_key), [draft])
  const sourceDuration = Math.max(2, Number(draft?.source_video_duration_seconds || sourceAsset?.duration_seconds || 15))
  const startSliderMax = Math.max(0, sourceDuration - 2)
  const clipLength = clipEnd - clipStart
  const tailOffset = clipEnd - clipStart
  const availableTailMax = Math.min(15, Math.max(2, sourceDuration - clipStart))
  const middleReferenceFrames = referenceFrameTimes
    .map((seconds, timeIndex) => ({ seconds, timeIndex }))
    .filter(({ seconds }) => seconds > clipStart + 0.05 && seconds < clipEnd - 0.05)
  const frameOrderValid = referenceMode !== 'multi_reference_video' || middleReferenceFrames.length > 0
  const clipDurationValid = clipLength >= 2 && clipLength <= 15
  const clipSelectionValid = frameOrderValid && clipDurationValid
  const refreshReferenceFrames = async (times: number[]) => {
    if (!draft) return
    setReferenceFrameLoading(true)
    try {
      const response = await videoGenApi.clipTemplateDraft(projectId, draft.id, {
        clip_start_seconds: clipStart,
        clip_end_seconds: clipEnd,
        middle_seconds: times,
      })
      setDraft(response.data)
      setReferenceFrameTimes(response.data.reference_frame_times || times)
      if (response.data.middle_seconds !== undefined && response.data.middle_seconds !== null) {
        setMiddleSeconds(response.data.middle_seconds)
      }
    } finally {
      setReferenceFrameLoading(false)
    }
  }

  const chooseReferenceMode = async (mode: TemplateGenerationMode) => {
    if (mode === 'image_to_video') {
      setReferenceFrameTimes([])
      setReferenceMode(mode)
      return
    }
    if (mode === 'first_last_frame_video') {
      await refreshReferenceFrames([clipEnd])
      setReferenceMode(mode)
      return
    }
    const midpoint = Number((clipStart + clipLength / 2).toFixed(1))
    const nextTimes = [...referenceFrameTimes]
    if (!nextTimes.some((value) => value < clipEnd - 0.05)) nextTimes.push(midpoint)
    if (!nextTimes.some((value) => Math.abs(value - clipEnd) < 0.05)) nextTimes.push(clipEnd)
    await refreshReferenceFrames([...new Set(nextTimes)].sort((a, b) => a - b))
    setReferenceMode(mode)
  }

  const addReferenceFrame = async () => {
    if (1 + referenceFrameTimes.length >= MAX_REFERENCE_IMAGES) {
      message.info(`最多支持 ${MAX_REFERENCE_IMAGES} 张总参考图（含首帧和尾帧）`)
      return
    }
    const duration = Math.max(0.1, clipLength)
    const grid = Array.from({ length: 8 }, (_, index) => clipStart + duration * (index + 1) / 9)
    const candidate = referenceFrameTimes.length === 0
      ? clipEnd
      : grid.find((value) => !referenceFrameTimes.some((selected) => Math.abs(selected - value) < 0.05))
    if (candidate === undefined) {
      message.warning('当前片段没有可用的新时间点，请先调整时间轴')
      return
    }
    await refreshReferenceFrames([...referenceFrameTimes, candidate].sort((a, b) => a - b))
    setReferenceMode('multi_reference_video')
  }

  const autoSampleConstructionFrames = async () => {
    const duration = Math.max(2, clipLength)
    const times = Array.from({ length: MAX_REFERENCE_IMAGES - 1 }, (_, index) => {
      const ratio = (index + 1) / (MAX_REFERENCE_IMAGES - 1)
      return Number((clipStart + duration * ratio).toFixed(3))
    })
    await refreshReferenceFrames(times)
    setReferenceMode('multi_reference_video')
    message.success('已按施工节奏均匀提取 9 张关键帧')
  }

  const addReferenceAtTime = async (rawSeconds: number) => {
    if (1 + referenceFrameTimes.length >= MAX_REFERENCE_IMAGES) {
      message.info(`最多支持 ${MAX_REFERENCE_IMAGES} 张总参考图（含首帧和尾帧）`)
      return
    }
    const candidate = Number(Number(rawSeconds).toFixed(3))
    if (!Number.isFinite(candidate) || candidate <= clipStart + 0.05 || candidate >= clipEnd - 0.05) {
      message.warning('中间帧必须位于首帧和尾帧之间')
      return
    }
    if (referenceFrameTimes.some((selected) => Math.abs(selected - candidate) < 0.05)) {
      message.info('这个时间点已经加入参考帧')
      return
    }
    const nextTimes = referenceFrameTimes.filter((value) => Math.abs(value - clipEnd) >= 0.05)
    nextTimes.push(candidate, clipEnd)
    await refreshReferenceFrames([...new Set(nextTimes)].sort((a, b) => a - b))
    setReferenceMode('multi_reference_video')
  }

  const updateMiddleFrameTime = async (timeIndex: number, rawSeconds: number | null) => {
    const candidate = Number(Number(rawSeconds ?? 0).toFixed(3))
    if (!Number.isFinite(candidate) || candidate <= clipStart + 0.05 || candidate >= clipEnd - 0.05) {
      message.warning('中间帧必须位于首帧和尾帧之间')
      return
    }
    if (referenceFrameTimes.some((selected, index) => index !== timeIndex && Math.abs(selected - candidate) < 0.05)) {
      message.warning('中间帧时间不能重复')
      return
    }
    const nextTimes = referenceFrameTimes.map((value, index) => index === timeIndex ? candidate : value)
    await refreshReferenceFrames([...new Set(nextTimes)].sort((a, b) => a - b))
    setMiddleSeconds(candidate)
    seekPreview(candidate, '中间帧')
  }

  const removeMiddleFrame = async (timeIndex: number) => {
    const target = referenceFrameTimes[timeIndex]
    if (target === undefined || Math.abs(target - clipEnd) < 0.05) return
    const nextTimes = referenceFrameTimes.filter((_, index) => index !== timeIndex)
    await refreshReferenceFrames(nextTimes)
    setReferenceMode(nextTimes.length === 0 ? 'image_to_video' : nextTimes.some((value) => value < clipEnd - 0.05) ? 'multi_reference_video' : 'first_last_frame_video')
  }

  const removeTailFrame = async () => {
    if (middleReferenceFrames.length > 0) {
      message.info('存在中间帧时，尾帧不能删除。请先删除中间帧。')
      return
    }
    if (!referenceFrameTimes.some((value) => Math.abs(value - clipEnd) < 0.05)) return
    await refreshReferenceFrames(referenceFrameTimes.filter((value) => Math.abs(value - clipEnd) >= 0.05))
    setReferenceMode('image_to_video')
  }

  const handleAddReferenceByPlus = () => {
    if (referenceMode === 'image_to_video') void chooseReferenceMode('first_last_frame_video')
    else if (referenceMode === 'first_last_frame_video') void chooseReferenceMode('multi_reference_video')
    else void addReferenceFrame()
  }

  const seekPreview = (seconds: number, marker = '当前时间') => {
    const nextTime = Math.max(0, Math.min(sourceDuration, Number(seconds) || 0))
    setPreviewTime(nextTime)
    setPreviewMarker(marker)
    if (videoRef.current) {
      videoRef.current.currentTime = nextTime
      videoRef.current.pause()
    }
  }

  const updateClipStart = (value: number | null) => {
    const nextStart = Math.max(0, Math.min(Number(value ?? clipStart), startSliderMax))
    const preservedTailOffset = Math.min(Math.max(2, tailOffset), Math.max(2, sourceDuration - nextStart))
    const preservedMiddleOffset = Math.min(Math.max(0.1, middleSeconds - clipStart), Math.max(0.1, preservedTailOffset - 0.1))
    const nextEnd = nextStart + preservedTailOffset
    setClipStart(nextStart)
    setMiddleSeconds(nextStart + preservedMiddleOffset)
    setClipEnd(nextEnd)
    setReferenceFrameTimes((current) => current.map((seconds) => {
      const shifted = nextStart + (seconds - clipStart)
      return Math.abs(seconds - clipEnd) < 0.05
        ? nextEnd
        : Math.max(nextStart + 0.1, Math.min(shifted, nextEnd - 0.1))
    }).sort((a, b) => a - b))
    seekPreview(nextStart, '首帧')
  }

  const updateClipEndTime = (value: number | null) => {
    const previousEnd = clipEnd
    const nextEnd = Math.max(clipStart + 2, Math.min(Number(value ?? clipEnd), clipStart + availableTailMax))
    setClipEnd(nextEnd)
    setReferenceFrameTimes((current) => {
      const middleTimes = current.filter((seconds) => Math.abs(seconds - previousEnd) >= 0.05 && seconds < nextEnd - 0.05)
      return [...middleTimes, nextEnd].sort((a, b) => a - b)
    })
    if (middleSeconds >= nextEnd) setMiddleSeconds(Math.max(clipStart + 0.1, nextEnd - 0.1))
    seekPreview(nextEnd, '尾帧')
  }

  const refreshDraft = async (draftId: string) => {
    const response = await videoGenApi.getTemplateDraft(projectId, draftId)
    setDraft(response.data)
    if (response.data.prompt_recipe) {
      setRecipe(response.data.prompt_recipe)
      const savedMode = response.data.prompt_recipe.generation_modes?.[0] as TemplateGenerationMode | undefined
      const savedTimes = response.data.reference_frame_times || []
      if (savedTimes.length) setReferenceFrameTimes(savedTimes)
      else if (savedMode === 'first_last_frame_video' && response.data.clip_end_seconds !== undefined) setReferenceFrameTimes([response.data.clip_end_seconds])
      else if (savedMode === 'multi_reference_video' && response.data.middle_seconds !== undefined && response.data.clip_end_seconds !== undefined) setReferenceFrameTimes([response.data.middle_seconds, response.data.clip_end_seconds])
      setReferenceMode(savedMode || (savedTimes.length === 0 ? 'image_to_video' : savedTimes.length === 1 ? 'first_last_frame_video' : 'multi_reference_video'))
    }
    if (response.data.name) setTemplateName(response.data.name)
    if (response.data.description) setDescription(response.data.description)
    if (response.data.clip_start_seconds !== undefined && response.data.clip_start_seconds !== null) setClipStart(response.data.clip_start_seconds)
    if (response.data.clip_end_seconds !== undefined && response.data.clip_end_seconds !== null) setClipEnd(response.data.clip_end_seconds)
    if (response.data.middle_seconds !== undefined && response.data.middle_seconds !== null) setMiddleSeconds(response.data.middle_seconds)
    return response.data
  }

  useEffect(() => {
    if (!projectId || restoreStartedRef.current) return
    restoreStartedRef.current = true
    const savedDraftId = window.localStorage.getItem(templateDraftStorageKey(projectId))
    let cancelled = false
    const restore = async () => {
      try {
        let draftId = savedDraftId
        if (!draftId) {
          const list = await videoGenApi.listTemplateDrafts(projectId)
          const candidate = list.data.find((item) => item.prompt_recipe || item.preview_job_id || ['frames_ready', 'analyzed', 'previewing', 'ready'].includes(item.status))
          if (!candidate) {
            const latest = list.data[0]
            if (!latest) return
            draftId = latest.id
          } else {
            draftId = candidate.id
          }
          window.localStorage.setItem(templateDraftStorageKey(projectId), draftId)
        }
        if (activeDraftIdRef.current && activeDraftIdRef.current !== draftId) return
        activeDraftIdRef.current = draftId
        const next = await refreshDraft(draftId)
        if (cancelled || activeDraftIdRef.current !== draftId) return
        const savedTimes = next.reference_frame_times || []
        const savedMode = next.prompt_recipe?.generation_modes?.[0] as TemplateGenerationMode | undefined
        if (savedTimes.length && !savedMode) {
          setReferenceMode(savedTimes.length === 1 ? 'first_last_frame_video' : 'multi_reference_video')
          setReferenceFrameTimes(savedTimes)
        }
        const hasPreview = Boolean(next.preview_job_id) || ['previewing', 'ready', 'published'].includes(next.status)
        const restoredStep = hasPreview ? 5 : next.prompt_recipe ? 4 : next.first_frame_asset_id ? 2 : next.clip_start_seconds !== null && next.clip_start_seconds !== undefined ? 1 : next.source_video_asset_id ? 1 : 0
        setMaxStep(restoredStep)
        setStep(restoredStep)
        if (next.preview_job_id) {
          try {
            const job = await videoGenApi.getTask(projectId, next.preview_job_id)
            if (!cancelled) {
              setPreviewJob(job.data)
              setPreviewRequested(true)
            }
          } catch {
            // 草稿仍可恢复，试生成任务查询失败时允许重新提交。
          }
        }
        message.info('已恢复上次未完成的模板草稿')
      } catch {
        window.localStorage.removeItem(templateDraftStorageKey(projectId))
      }
    }
    void restore()
    return () => {
      cancelled = true
    }
  }, [projectId, message])

  useEffect(() => {
    videoGenApi.providers(projectId).then((response) => {
      const list = response.data || []
      setProviders(list)
      const active = list.find((item: any) => item.is_active && item.available) || list.find((item: any) => item.available)
      if (active) {
        setPreviewProvider(active.provider)
        setPreviewModel(active.default_model || active.models?.[0] || '')
      }
    }).catch(() => {})
  }, [projectId])

  useEffect(() => {
    if (!projectId) return
    setLibraryLoading(true)
    assetApi.list(projectId, 'video')
      .then((response) => setVideoAssets(response.data || []))
      .catch(() => setVideoAssets([]))
      .finally(() => setLibraryLoading(false))
  }, [projectId])

  useEffect(() => {
    if (!previewJob?.id || ['success', 'failed', 'cancelled'].includes(previewJob.status)) return
    let stopped = false
    const timer = window.setInterval(async () => {
      try {
        const response = await videoGenApi.getTask(projectId, previewJob.id)
        if (stopped) return
        setPreviewJob(response.data)
        if (response.data.status === 'success') {
          const next = await refreshDraft(draft?.id || '')
          setDraft(next)
          message.success('试生成完成，视频已加入素材库')
        }
      } catch {
        // 继续轮询，短暂网络错误不影响任务
      }
    }, 1500)
    return () => {
      stopped = true
      window.clearInterval(timer)
    }
  }, [previewJob?.id, previewJob?.status, projectId, draft?.id, message])

  const handleUpload = async (file: File) => {
    setUploading(true)
    try {
      const assetResponse = await assetApi.upload(projectId, file, file.name)
      const asset = assetResponse.data
      if (asset.asset_type !== 'video') {
        message.error('请选择视频文件')
        return false
      }
      // 名称和用途说明在关键帧分析完成后由 AI 生成；上传阶段只保留一个可识别的草稿名。
      const draftResponse = await videoGenApi.createTemplateDraft(projectId, {
        source_video_asset_id: asset.id,
        name: '待 AI 生成模板名称',
      })
      setSourceAsset(asset)
      setVideoAssets((items) => [asset, ...items.filter((item) => item.id !== asset.id)])
      setDraft(draftResponse.data)
      activeDraftIdRef.current = draftResponse.data.id
      window.localStorage.setItem(templateDraftStorageKey(projectId), draftResponse.data.id)
      setTemplateName('')
      setDescription('')
      setPreviewTime(0)
      setPreviewMarker('当前时间')
      setReferenceFrameTimes([])
      setReferenceMode('image_to_video')
      setClipEnd(Math.min(5, draftResponse.data.source_video_duration_seconds || 5))
      setMiddleSeconds(Math.min(2.5, (draftResponse.data.source_video_duration_seconds || 5) / 2))
      setStep(1)
      setMaxStep(1)
      message.success('视频已上传，开始选择镜头')
    } catch {
      // 请求拦截器统一提示
    } finally {
      setUploading(false)
    }
    return false
  }

  const handleSelectLibraryAsset = async (asset: Asset) => {
    setSelectingLibrary(true)
    setSelectingAssetId(asset.id)
    try {
      const response = await videoGenApi.createTemplateDraft(projectId, {
        source_video_asset_id: asset.id,
        name: '待 AI 生成模板名称',
      })
      const nextDraft = response.data
      setSourceAsset(asset)
      setDraft(nextDraft)
      activeDraftIdRef.current = nextDraft.id
      window.localStorage.setItem(templateDraftStorageKey(projectId), nextDraft.id)
      setTemplateName('')
      setDescription('')
      setPreviewTime(0)
      setPreviewMarker('当前时间')
      setReferenceFrameTimes([])
      setReferenceMode('image_to_video')
      setClipStart(0)
      setClipEnd(Math.min(5, nextDraft.source_video_duration_seconds || 5))
      setMiddleSeconds(Math.min(2.5, (nextDraft.source_video_duration_seconds || 5) / 2))
      setLibraryOpen(false)
      setStep(1)
      setMaxStep(1)
      message.success(`已选择素材：${asset.name}`)
    } catch {
      // 请求拦截器统一提示
    } finally {
      setSelectingLibrary(false)
      setSelectingAssetId(null)
    }
  }

  const formatAssetTime = (value?: string) => {
    if (!value) return '-'
    const date = new Date(value)
    return Number.isNaN(date.getTime()) ? '-' : date.toLocaleString('zh-CN', { hour12: false })
  }

  const formatAssetDuration = (value?: number) => {
    if (!value || value <= 0) return '选择后自动读取'
    const seconds = Math.round(value * 10) / 10
    return `${seconds.toFixed(seconds % 1 ? 1 : 0)} 秒`
  }

  const assetSourceLabel = (source?: string) => ({
    upload: '上传素材',
    ai_video: 'AI 试生成',
    render: '视频工程成片',
  }[source || ''] || source || '项目素材')

  const handleClip = async () => {
    if (!draft) return
    if (!clipDurationValid) {
      message.warning('片段长度需要在 2-15 秒之间')
      return
    }
    if (!frameOrderValid) {
      message.warning('关键帧顺序应为：首帧 < 中间帧 < 尾帧')
      return
    }
    setProcessing(true)
    try {
      const selectedTimes = referenceMode === 'image_to_video'
        ? []
        : referenceMode === 'first_last_frame_video'
          ? [clipEnd]
          : referenceFrameTimes
      const response = await videoGenApi.clipTemplateDraft(projectId, draft.id, {
        clip_start_seconds: clipStart,
        clip_end_seconds: clipEnd,
        middle_seconds: selectedTimes,
      })
      setDraft(response.data)
      setReferenceFrameTimes(response.data.reference_frame_times || selectedTimes)
      setMaxStep(Math.max(maxStep, 2))
      setStep(2)
      message.success(`镜头已截取，使用 ${1 + selectedTimes.length} 张参考图`)
    } finally {
      setProcessing(false)
    }
  }

  const handleAnalyze = async () => {
    if (!draft) return
    setProcessing(true)
    try {
      const response = await videoGenApi.analyzeTemplateDraft(projectId, draft.id, intent.trim(), referenceMode)
      setDraft(response.data)
      setTemplateName(response.data.name || '')
      setDescription(response.data.description || '')
      setRecipe(response.data.prompt_recipe || {})
      setMaxStep(Math.max(maxStep, 4))
      setStep(4)
      message.success('模板配方已生成，可以编辑后试生成')
    } finally {
      setProcessing(false)
    }
  }

  const updateRecipe = (key: string, value: any) => setRecipe((current) => ({ ...current, [key]: value }))

  const saveRecipe = async () => {
    if (!draft) return
    const nextRecipe = { ...recipe, prompt: recipeText(recipe, 'prompt') }
    const response = await videoGenApi.updateTemplateDraftRecipe(projectId, draft.id, {
      name: templateName.trim() || draft.name,
      description: description.trim(),
      prompt_recipe: nextRecipe,
    })
    setDraft(response.data)
    setRecipe(response.data.prompt_recipe || nextRecipe)
  }

  const handlePreview = async (structureConflictConfirmed = false) => {
    if (!draft) return
    await saveRecipe()
    const previewPrompt = String(recipe.prompt || '').trim()
    if (!structureConflictConfirmed && previewPrompt) {
      try {
        const check = await videoGenApi.constraintCheck(projectId, previewPrompt, recipe)
        if (check.data.blocked) {
          Modal.confirm({
            title: '检测到可能改变工程结构的描述',
            icon: <SafetyOutlined />,
            content: (
              <div>
                <p style={{ marginBottom: 8 }}>系统识别到：{check.data.conflicts.join('、')}。</p>
                <p style={{ marginBottom: 0, color: '#667085' }}>
                  如果这里描述的是临时支撑、模板或施工工序，而不是修改整栋建筑，可以确认继续。本次确认只对当前试生成生效。
                </p>
              </div>
            ),
            okText: '确认继续试生成',
            cancelText: '返回修改',
            okButtonProps: { danger: true },
            onOk: () => handlePreview(true),
          })
          return
        }
      } catch {
        // 后端仍会执行最终校验
      }
    }
    setPreviewRequested(true)
    setProcessing(true)
    try {
      const response = await videoGenApi.previewTemplateDraft(projectId, draft.id, {
        provider: previewProvider || undefined,
        model_name: previewModel || undefined,
        // 试生成时长沿用当前选中的镜头片段，参考图时序则由后端从片段起点重新计算。
        duration: Math.max(2, Math.min(15, Math.round(clipLength))),
        aspect_ratio: String(recipe?.recommended?.aspect_ratio || 'adaptive'),
        resolution: String(recipe?.recommended?.resolution || '720p'),
        structure_conflict_confirmed: structureConflictConfirmed,
      })
      setPreviewJob(response.data)
      if (response.data.status === 'success') {
        const next = await refreshDraft(draft.id)
        setDraft(next)
        message.success('试生成完成，视频已加入素材库')
      } else {
        message.info('试生成任务已提交，请等待结果')
      }
    } finally {
      setProcessing(false)
    }
  }

  const handlePublish = async () => {
    if (!draft) return
    setPublishing(true)
    try {
      await saveRecipe()
      await videoGenApi.publishTemplateDraft(projectId, draft.id, {
        name: templateName.trim() || draft.name,
        description: description.trim() || undefined,
        category: String(recipe.category || '建筑外景运镜'),
        tags: Array.isArray(recipe.tags) ? recipe.tags : [],
        scope: publishScope,
      })
      window.localStorage.removeItem(templateDraftStorageKey(projectId))
      message.success('模板已发布，试生成视频已保存在素材库')
      navigate(`/project/${projectId}/ai-video`)
    } finally {
      setPublishing(false)
    }
  }

  const activeReferenceCards = useMemo(() => {
    const fileKeys = draft?.reference_frame_file_keys || []
    const cards: Array<{ key: string; label: string; seconds: number; url: string; timeIndex?: number; removable?: boolean }> = [{
      key: 'first',
      label: '首帧',
      seconds: Number(draft?.clip_start_seconds ?? clipStart),
      url: fileUrl(fileKeys[0]) || firstFrameUrl,
    }]
    let middleIndex = 1
    referenceFrameTimes.forEach((seconds, index) => {
      const isLast = Math.abs(seconds - clipEnd) < 0.05
      cards.push({
        key: `${isLast ? 'last' : 'middle'}-${index}`,
        label: isLast ? '尾帧' : `中间帧 ${middleIndex++}`,
        seconds,
        url: fileUrl(fileKeys[index + 1]) || (isLast ? lastFrameUrl : middleFrameUrl),
        timeIndex: index,
        removable: !isLast,
      })
    })
    return cards
  }, [clipEnd, clipStart, draft, firstFrameUrl, lastFrameUrl, middleFrameUrl, referenceFrameTimes])

  const inferredDraftStep = useMemo(() => {
    if (!draft) return 0
    if (draft.preview_job_id || ['previewing', 'ready', 'published'].includes(draft.status)) return 5
    if (draft.prompt_recipe) return 4
    if (draft.first_frame_asset_id) return 2
    return 1
  }, [draft])
  const currentStep = draft && step === 0 ? inferredDraftStep : step
  const canContinue = currentStep === 0 ? !!draft : currentStep === 1 ? !!draft && clipSelectionValid : currentStep === 2 ? !!draft?.first_frame_asset_id : currentStep === 3 ? !!draft : !!recipe.prompt

  const goNext = () => {
    if (currentStep === 0 && !draft) {
      message.warning('请先上传专业视频')
      return
    }
    if (currentStep === 1) {
      void handleClip()
      return
    }
    if (currentStep === 2) {
      setMaxStep(Math.max(maxStep, 3))
      setStep(3)
      return
    }
    if (currentStep === 3) {
      void handleAnalyze()
      return
    }
    if (currentStep === 4) {
      void saveRecipe().then(() => {
        setMaxStep(Math.max(maxStep, 5))
        setStep(5)
      })
      return
    }
    if (currentStep === 5) {
      if (!previewRequested || previewJob?.status !== 'success') void handlePreview()
      else void handlePublish()
    }
  }

  const goBack = () => {
    if (currentStep >= 4 && draft && recipe.prompt) void saveRecipe()
    setStep(Math.max(1, currentStep - 1))
  }

  return (
    <div className="video-template-creator-page">
      <nav className="video-template-process" aria-label="模板创建流程">
        {STEPS.map((item, index) => {
          const isComplete = index < currentStep
          const isCurrent = index === currentStep
          const isAvailable = index <= Math.max(maxStep, currentStep)
          return (
            <button
              type="button"
              key={item.title}
              className={`video-template-process-item${isCurrent ? ' is-current' : ''}${isComplete ? ' is-complete' : ''}`}
              onClick={() => isAvailable && setStep(index)}
              disabled={!isAvailable}
              aria-current={isCurrent ? 'step' : undefined}
            >
              <span className="video-template-process-node">{isComplete ? <CheckCircleOutlined /> : item.icon}</span>
              <span className="video-template-process-copy">
                <span className="video-template-process-title">{item.title}</span>
                <span className="video-template-process-description">{item.description}</span>
              </span>
            </button>
          )
        })}
      </nav>

      <main className="video-template-main-card">
        {currentStep === 0 && (
          <div>
            <Title level={5}>上传或选择专业视频</Title>
            <Paragraph type="secondary">可以上传新视频，也可以直接从当前项目素材库选择已有视频。选中后会展示入库时间、原始时长和分辨率，并继续截取连续镜头。</Paragraph>
            <Row gutter={[20, 20]}>
              <Col xs={24} lg={15}>
                <Dragger
                  className="video-template-dropzone"
                  accept=".mp4,.mov,.avi,.mkv,.webm"
                  multiple={false}
                  showUploadList={false}
                  beforeUpload={handleUpload}
                  disabled={uploading}
                >
                  {uploading ? <Spin /> : <><p className="ant-upload-drag-icon"><CloudUploadOutlined /></p><p className="ant-upload-text">点击或拖拽专业视频到这里</p><p className="ant-upload-hint">支持 MP4、MOV、AVI、MKV、WebM，建议选择 2-15 秒的连续镜头</p></>}
                </Dragger>
              </Col>
              <Col xs={24} lg={9}>
                <Card className="video-template-upload-guide" size="small" title="上传后会自动完成">
                  <Space direction="vertical" size={14} style={{ width: '100%' }}>
                    <Text>① 从样片截取一个连续镜头</Text>
                    <Text>② 提取首帧、中间帧和尾帧</Text>
                    <Text>③ AI 生成模板名称、说明和提示词</Text>
                    <Divider className="video-template-choice-divider" plain>或者</Divider>
                    <Button
                      type="default"
                      className="video-template-library-link"
                      icon={<VideoCameraOutlined />}
                      onClick={() => setLibraryOpen(true)}
                      disabled={uploading || selectingLibrary}
                    >
                      从素材库选择已有视频{videoAssets.length ? `（${videoAssets.length} 个）` : ''}
                    </Button>
                  </Space>
                </Card>
              </Col>
            </Row>
            {draft && <Alert type="success" showIcon message={`已选择：${draft.source_video_name || '专业视频'}`} description="素材已关联到当前模板草稿，可以继续截取镜头。" style={{ marginTop: 18 }} />}

            <Modal
              title="从素材库选择专业视频"
              open={libraryOpen}
              onCancel={() => setLibraryOpen(false)}
              footer={null}
              width={780}
              destroyOnClose
            >
              <Alert
                type="info"
                showIcon
                style={{ marginBottom: 16 }}
                message="选择后会直接进入镜头截取"
                description="入库时间用于确认素材来源；原始时长和分辨率会在选择时自动读取。"
              />
              {libraryLoading ? <div style={{ textAlign: 'center', padding: 32 }}><Spin /></div> : videoAssets.length ? (
                <Row gutter={[12, 12]}>
                  {videoAssets.map((asset) => (
                    <Col xs={24} md={12} key={asset.id}>
                      <Card
                        size="small"
                        hoverable
                        onClick={() => void handleSelectLibraryAsset(asset)}
                        loading={selectingLibrary && selectingAssetId === asset.id}
                        title={<Space><VideoCameraOutlined style={{ color: '#2563eb' }} /><span style={{ maxWidth: 240, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{asset.name}</span></Space>}
                        extra={<Tag color={asset.source === 'upload' ? 'blue' : 'purple'}>{assetSourceLabel(asset.source)}</Tag>}
                      >
                        <Descriptions size="small" column={1} bordered>
                          <Descriptions.Item label="入库时间">{formatAssetTime(asset.created_at)}</Descriptions.Item>
                          <Descriptions.Item label="原始时长">{formatAssetDuration(asset.duration_seconds)}</Descriptions.Item>
                          <Descriptions.Item label="分辨率">{asset.width && asset.height ? `${asset.width} × ${asset.height}` : '选择后自动读取'}</Descriptions.Item>
                        </Descriptions>
                        <Button type="link" block style={{ paddingBottom: 0 }} loading={selectingLibrary && selectingAssetId === asset.id}>选择此视频</Button>
                      </Card>
                    </Col>
                  ))}
                </Row>
              ) : <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="当前项目素材库还没有视频" />}
            </Modal>
          </div>
        )}

        {currentStep === 1 && draft && (
          <div className="video-template-clip-workspace">
            <Title level={5}>截取一个连续镜头</Title>
            <Paragraph type="secondary">先确定连续镜头范围，再选择模板使用的参考帧。默认只发送首帧，后续可以通过类型选择或加号增加尾帧和中间帧。</Paragraph>
            <div className="video-template-preview-layout">
              <div className="video-template-video-stage">
                <Card size="small" title="视频预览" className="video-template-preview-card">
                  {sourceVideoUrl ? <video
                    ref={videoRef}
                    controls
                    muted
                    src={sourceVideoUrl}
                    onLoadedMetadata={() => seekPreview(previewTime)}
                    style={{ width: '100%', background: '#111827', borderRadius: 8 }}
                  /> : <Empty description="视频预览不可用" />}
                  <div className="video-template-preview-status">
                    <Tag color="blue">当前预览：{previewMarker} · {previewTime.toFixed(1)} 秒</Tag>
                    <Text type="secondary">拖动下方时间轴，视频会暂停并跳到对应帧</Text>
                    {referenceMode === 'multi_reference_video' && (
                      <Button
                        size="small"
                        type="link"
                        icon={<PlusOutlined />}
                        disabled={previewTime <= clipStart + 0.05 || previewTime >= clipEnd - 0.05}
                        onClick={() => void addReferenceAtTime(previewTime)}
                      >
                        加入当前帧
                      </Button>
                    )}
                  </div>
                </Card>
              </div>
              <Card size="small" title="模板参考帧" className="video-template-reference-panel">
                <div className="video-template-reference-heading">
                  <Text strong>参考帧类型</Text>
                  <Tag color={referenceMode === 'multi_reference_video' ? 'cyan' : 'blue'}>{activeReferenceCards.length} 张</Tag>
                </div>
                <div className="video-template-reference-control">
                  <Select
                    size="small"
                    value={referenceMode}
                    onChange={(value) => void chooseReferenceMode(value as TemplateGenerationMode)}
                    options={Object.entries(TEMPLATE_MODE_LABELS).map(([value, label]) => ({ value, label }))}
                    loading={referenceFrameLoading}
                  />
                  <Tooltip
                    title={referenceMode === 'image_to_video'
                      ? '添加尾帧，切换为首尾帧生成'
                      : referenceMode === 'first_last_frame_video'
                        ? '添加中间帧，切换为多图生成'
                        : activeReferenceCards.length >= MAX_REFERENCE_IMAGES
                          ? `已达到 ${MAX_REFERENCE_IMAGES} 张上限`
                          : '再添加一张中间帧'}
                  >
                    <Button
                      size="small"
                      type="primary"
                      ghost
                      aria-label={referenceMode === 'image_to_video' ? '添加尾帧' : '添加中间帧'}
                      icon={<PlusOutlined />}
                      loading={referenceFrameLoading}
                      disabled={activeReferenceCards.length >= MAX_REFERENCE_IMAGES}
                      onClick={handleAddReferenceByPlus}
                    />
                  </Tooltip>
                  <Button
                    size="small"
                    icon={<ThunderboltOutlined />}
                    loading={referenceFrameLoading}
                    onClick={() => void autoSampleConstructionFrames()}
                  >
                    自动提取施工节奏（9帧）
                  </Button>
                </div>
                <Text type="secondary" className="video-template-reference-note">
                  {referenceMode === 'image_to_video'
                    ? '仅发送首帧，片段沿用默认时长。'
                    : referenceMode === 'first_last_frame_video'
                      ? '首帧和尾帧共同控制画面变化。'
                      : `可继续添加中间帧，最多 ${MAX_REFERENCE_IMAGES} 张总参考图。`}
                </Text>
                <Text type="secondary" className="video-template-reference-note">
                  参考帧只影响发送给 AI 的图片，不改变视频截取范围。
                </Text>
              </Card>
            </div>
            <Card size="small" title="拖动时间轴选择关键帧" className="video-template-timeline-card">
              <div className="video-template-timeline-full-width">
                  <div className="video-template-timeline-row">
                    <div className="video-template-timeline-label">
                      <Text strong>首帧时间</Text>
                    </div>
                    <div className="video-template-timeline-track">
                      <Slider
                        min={0}
                        max={startSliderMax}
                        step={0.1}
                        value={clipStart}
                        onChange={(value) => updateClipStart(Number(value))}
                        tooltip={{ formatter: (value) => value === undefined ? '' : `${value.toFixed(1)} 秒` }}
                      />
                    </div>
                    <div className="video-template-timeline-value">
                      <InputNumber controls={false} size="small" min={0} max={startSliderMax} step={0.1} precision={1} value={clipStart} onChange={updateClipStart} />
                      <Text type="secondary">秒</Text>
                    </div>
                  </div>
                  {referenceMode === 'multi_reference_video' && middleReferenceFrames.map((frame, displayIndex) => (
                    <div className="video-template-timeline-row" key={`timeline-middle-${frame.timeIndex}`}>
                      <div className="video-template-timeline-label">
                        <Space size={4}>
                          <Text strong>中间帧 {displayIndex + 1}</Text>
                          <Tooltip title={`删除中间帧 ${displayIndex + 1}`}>
                            <Button
                              type="text"
                              size="small"
                              danger
                              className="video-template-timeline-delete"
                              icon={<DeleteOutlined />}
                              aria-label={`删除中间帧 ${displayIndex + 1}`}
                              disabled={referenceFrameLoading}
                              onClick={() => void removeMiddleFrame(frame.timeIndex)}
                            />
                          </Tooltip>
                        </Space>
                      </div>
                      <div className="video-template-timeline-track">
                        <Slider
                          min={clipStart + 0.1}
                          max={Math.max(clipStart + 0.2, clipEnd - 0.1)}
                          step={0.1}
                          value={frame.seconds}
                          onChange={(value) => {
                            const nextTime = Number(value)
                            setReferenceFrameTimes((current) => current.map((seconds, index) => index === frame.timeIndex ? nextTime : seconds))
                            if (displayIndex === 0) setMiddleSeconds(nextTime)
                            seekPreview(nextTime, `中间帧 ${displayIndex + 1}`)
                          }}
                          onChangeComplete={(value) => void updateMiddleFrameTime(frame.timeIndex, Number(value))}
                          tooltip={{ formatter: (value) => value === undefined ? '' : `${value.toFixed(1)} 秒` }}
                        />
                      </div>
                      <div className="video-template-timeline-value">
                        <InputNumber
                          controls={false}
                          size="small"
                          min={clipStart + 0.1}
                          max={clipEnd - 0.1}
                          step={0.1}
                          precision={1}
                          value={frame.seconds}
                          onChange={(value) => void updateMiddleFrameTime(frame.timeIndex, value)}
                        />
                        <Text type="secondary">秒</Text>
                      </div>
                    </div>
                  ))}
                  {referenceMode !== 'image_to_video' && (
                    <div className="video-template-timeline-row">
                      <div className="video-template-timeline-label">
                        <Space size={4}>
                          <Text strong>尾帧位置</Text>
                          <Tooltip title={middleReferenceFrames.length > 0 ? '存在中间帧时尾帧不可删除' : '删除尾帧，切换回单图生成'}>
                            <Button
                              type="text"
                              size="small"
                              danger
                              className="video-template-timeline-delete"
                              icon={<DeleteOutlined />}
                              aria-label="删除尾帧"
                              disabled={middleReferenceFrames.length > 0 || referenceFrameLoading}
                              onClick={() => void removeTailFrame()}
                            />
                          </Tooltip>
                        </Space>
                      </div>
                      <div className="video-template-timeline-track">
                        <Slider
                          min={clipStart + 2}
                          max={clipStart + availableTailMax}
                          step={0.1}
                          value={clipEnd}
                          onChange={(value) => updateClipEndTime(Number(value))}
                          tooltip={{ formatter: (value) => value === undefined ? '' : `${value.toFixed(1)} 秒` }}
                        />
                      </div>
                      <div className="video-template-timeline-value">
                        <InputNumber
                          controls={false}
                          size="small"
                          min={clipStart + 2}
                          max={clipStart + availableTailMax}
                          step={0.1}
                          precision={1}
                          value={clipEnd}
                          onChange={updateClipEndTime}
                        />
                        <Text type="secondary">秒</Text>
                      </div>
                    </div>
                  )}
                  <div className={`video-template-clip-summary${clipSelectionValid ? '' : ' is-error'}`}>
                    <Text strong>片段 {Math.max(0, clipLength).toFixed(1)} 秒</Text>
                    <Text type={clipSelectionValid ? 'secondary' : 'danger'}>
                      {clipSelectionValid
                        ? referenceMode === 'image_to_video'
                          ? `首帧 ${clipStart.toFixed(1)}s，当前只发送 1 张参考图`
                          : `首帧 ${clipStart.toFixed(1)}s，尾帧 ${clipEnd.toFixed(1)}s，发送 ${activeReferenceCards.length} 张参考图`
                        : !frameOrderValid ? '请调整中间帧位置' : '片段时长需要在 2-15 秒之间'}
                    </Text>
                    <Text type="secondary">下一步仅确认已提取的参考帧</Text>
                  </div>
              </div>
            </Card>
            <Card size="small" title="来源素材" className="video-template-source-card">
                  <Descriptions size="small" column={4}>
                    <Descriptions.Item label="视频名称">{draft.source_video_name || sourceAsset?.name || '-'}</Descriptions.Item>
                    <Descriptions.Item label="入库时间">{formatAssetTime(sourceAsset?.created_at)}</Descriptions.Item>
                    <Descriptions.Item label="原始时长">{formatAssetDuration(draft.source_video_duration_seconds || sourceAsset?.duration_seconds)}</Descriptions.Item>
                    <Descriptions.Item label="分辨率">{sourceAsset?.width && sourceAsset?.height ? `${sourceAsset.width} × ${sourceAsset.height}` : '已在创建草稿时读取'}</Descriptions.Item>
                  </Descriptions>
            </Card>
          </div>
        )}

        {currentStep === 2 && draft && (
          <div>
            <Title level={5}>确认关键帧</Title>
            <Paragraph type="secondary">以下仅用于确认已经提取的参考帧和顺序。如需调整，请返回上一步修改。</Paragraph>
            <Row gutter={[16, 16]}>
              {activeReferenceCards.map((frame) => (
                <Col xs={24} sm={12} md={8} lg={6} key={frame.key}>
                  <Card
                    size="small"
                    title={frame.label}
                    extra={<Tag color="blue">{Number(frame.seconds || 0).toFixed(1)}s</Tag>}
                  >
                    {frame.url ? <img src={frame.url} alt={`${frame.label}预览`} style={{ width: '100%', aspectRatio: '4 / 3', objectFit: 'cover', borderRadius: 6 }} /> : <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="未提取" />}
                  </Card>
                </Col>
              ))}
            </Row>
            <Alert
              type="success"
              showIcon
              style={{ marginTop: 18 }}
              message={`已准备 ${activeReferenceCards.length} 张参考图`}
              description="下一步 AI 将按当前图片顺序生成视频模板配方。"
            />
          </div>
        )}

        {currentStep === 3 && (
          <div>
            <Title level={5}>AI 提炼模板配方</Title>
            <Paragraph type="secondary">补充模板用途后，提示词大师会把样片中的具体建筑泛化为“当前建筑主体”。</Paragraph>
            <Alert type="info" showIcon message="模板名称和用途说明会在本步骤根据关键帧由 AI 自动生成" description="下一步可以检查并编辑 AI 生成的名称、说明和提示词。" style={{ marginBottom: 16 }} />
            <Card size="small" title="模板用途补充" style={{ marginBottom: 16 }}>
              <Input.TextArea rows={3} value={intent} onChange={(event) => setIntent(event.target.value)} placeholder="例如：用于建筑外景总体展示，强调体量、立面和场地关系" />
            </Card>
            {draft?.prompt_recipe && <Alert type="info" showIcon message="已有分析结果" description="继续下一步会重新分析当前关键帧。" style={{ marginBottom: 16 }} />}
            <Card size="small" title="分析后会生成">
              <Space wrap>
                <Tag icon={<EyeOutlined />}>运镜类型</Tag><Tag>速度与方向</Tag><Tag>0%-100% 时间轴</Tag><Tag>建筑保持项</Tag><Tag>负向提示词</Tag><Tag>推荐参数</Tag>
              </Space>
            </Card>
          </div>
        )}

        {currentStep === 4 && (
          <div>
            <Title level={5}>模板提示词</Title>
            <Paragraph type="secondary">这里仅编辑 AI 生成的模板名称、说明、提示词和结构化配方。确认后进入独立的试生成与发布页面。</Paragraph>
            {!recipe.prompt && !draft?.prompt_recipe && <Alert type="warning" showIcon message="还没有模板配方" description="返回上一步运行 AI 提炼。" />}
            {(recipe.prompt || draft?.prompt_recipe) && (
              <Row gutter={[20, 20]}>
                <Col xs={24} lg={24}>
                  <Card size="small" title="AI 生成的模板信息" style={{ marginBottom: 12 }}>
                    <Space direction="vertical" style={{ width: '100%' }} size={12}>
                      <div>
                        <Text strong>模板名称</Text>
                        <Input value={templateName} onChange={(event) => setTemplateName(event.target.value)} placeholder="AI 生成后可编辑" maxLength={128} showCount style={{ marginTop: 6 }} />
                      </div>
                      <div>
                        <Text strong>用途说明</Text>
                        <Input.TextArea value={description} onChange={(event) => setDescription(event.target.value)} placeholder="AI 会根据关键帧生成适用场景说明" rows={3} maxLength={2000} showCount style={{ marginTop: 6 }} />
                      </div>
                    </Space>
                  </Card>
                  <Card size="small" title="可编辑的模板提示词">
                    <Input.TextArea rows={10} value={recipeText(recipe, 'prompt')} onChange={(event) => updateRecipe('prompt', event.target.value)} maxLength={500} showCount />
                    <Divider style={{ margin: '16px 0' }} />
                    <Space wrap>
                      <Tag color="blue">{recipe.category || '建筑外景运镜'}</Tag>
                      {(Array.isArray(recipe.tags) ? recipe.tags : []).map((tag: string) => <Tag key={tag}>{tag}</Tag>)}
                    </Space>
                  </Card>
                  <ConstructionRecipeEditor
                    value={recipe}
                    onChange={setRecipe}
                    defaultOpen={false}
                  />
                  <Card size="small" title="AI 生成的结构化配方" className="video-template-recipe-card">
                    {(() => {
                      const camera = recipeCamera(recipe.camera)
                      const timeline = recipeTimeline(recipe.timeline)
                      const preserve = recipeItems(recipe.preserve, ['锁定建筑主体数量、体量、轮廓、层数', '保持道路、主入口和主要构件位置', '保持首尾帧构图和空间关系'])
                      const allowChange = recipeItems(recipe.allow_change, ['轻微光影变化', '树木、云层、人物和车辆的自然微动'])
                      const negative = recipeItems(recipe.negative || recipe.negative_prompt, ['变形', '模糊', '结构错位', '透视错误'])
                      const recommended = recipe?.recommended && typeof recipe.recommended === 'object' ? recipe.recommended : {}
                      return (
                        <div className="video-template-recipe-content">
                          <div className="video-template-recipe-summary">
                            <Tag color="blue">{recipe.category || '建筑外景运镜'}</Tag>
                            {recipeItems(recipe.generation_modes).map((mode) => <Tag key={mode}>{mode}</Tag>)}
                            <Text type="secondary">模型已将镜头规则拆成可编辑字段</Text>
                          </div>

                          <section className="video-template-recipe-section">
                            <div className="video-template-recipe-section-title"><Text strong>运镜类型</Text><Text type="secondary">镜头路径与节奏</Text></div>
                            <div className="video-template-camera-grid">
                              {[
                                ['类型', camera.type],
                                ['速度', camera.speed],
                                ['方向', camera.direction],
                                ['路径', camera.path],
                                ['强度', camera.intensity],
                              ].map(([label, value]) => <div className="video-template-camera-item" key={label}><Text type="secondary">{label}</Text><Text strong>{String(value || '-')}</Text></div>)}
                            </div>
                          </section>

                          <section className="video-template-recipe-section">
                            <div className="video-template-recipe-section-title"><Text strong>时间轴</Text><Text type="secondary">0%-100% 镜头阶段</Text></div>
                            <div className="video-template-recipe-timeline">
                              {timeline.map((item, index) => {
                                const from = Math.max(0, Math.min(100, Number(item.from) || 0))
                                const to = Math.max(from, Math.min(100, Number(item.to) || 0))
                                return <div className="video-template-recipe-timeline-row" key={`${item.from}-${item.to}-${index}`}>
                                  <div className="video-template-recipe-timeline-label"><Text strong>{from}%-{to}%</Text><Text>{item.instruction}</Text></div>
                                  <div className="video-template-recipe-timeline-track"><span style={{ marginLeft: `${from}%`, width: `${Math.max(5, to - from)}%` }} /></div>
                                </div>
                              })}
                            </div>
                          </section>

                          <div className="video-template-recipe-list-grid">
                            <section className="video-template-recipe-section">
                              <div className="video-template-recipe-section-title"><Text strong>建筑保持项</Text><Text type="secondary">生成时锁定</Text></div>
                              <div className="video-template-recipe-tags">{preserve.map((item) => <Tag color="green" key={item}>{item}</Tag>)}</div>
                            </section>
                            <section className="video-template-recipe-section">
                              <div className="video-template-recipe-section-title"><Text strong>允许变化</Text><Text type="secondary">仅限自然微动</Text></div>
                              <div className="video-template-recipe-tags">{allowChange.map((item) => <Tag key={item}>{item}</Tag>)}</div>
                            </section>
                          </div>

                          <section className="video-template-recipe-section">
                            <div className="video-template-recipe-section-title"><Text strong>负向提示词</Text><Text type="secondary">自动加入生成约束</Text></div>
                            <div className="video-template-recipe-tags video-template-recipe-negative">{negative.map((item) => <Tag key={item}>{item}</Tag>)}</div>
                          </section>

                          <section className="video-template-recipe-section video-template-recommended-section">
                            <div className="video-template-recipe-section-title"><Text strong>推荐参数</Text><Text type="secondary">试生成会按此配置提交</Text></div>
                            <div className="video-template-recommended-grid">
                              <div><Text type="secondary">时长</Text><Text strong>{String(recommended.duration || '5 秒')}</Text></div>
                              <div><Text type="secondary">比例</Text><Text strong>{String(recommended.aspect_ratio || 'adaptive')}</Text></div>
                              <div><Text type="secondary">分辨率</Text><Text strong>{String(recommended.resolution || '720p')}</Text></div>
                            </div>
                          </section>
                        </div>
                      )
                    })()}
                  </Card>
                </Col>
              </Row>
            )}
          </div>
        )}

        {currentStep === 5 && (
          <div>
            <Title level={5}>试生成与发布</Title>
            <Paragraph type="secondary">模板提示词已确认。先试生成一次，确认运镜和建筑稳定性，再选择发布范围。</Paragraph>
            {!recipe.prompt && !draft?.prompt_recipe && <Alert type="warning" showIcon message="还没有模板配方" description="返回上一步编辑模板提示词。" />}
            {(recipe.prompt || draft?.prompt_recipe) && (
              <Row gutter={[20, 20]}>
                <Col xs={24} lg={16}>
                  <Card size="small" title="试生成结果">
                    <Space style={{ width: '100%', marginBottom: 12 }} align="center">
                      <Text type="secondary" style={{ fontSize: 12 }}>生成模型</Text>
                      <Select
                        size="small"
                        value={previewProvider || undefined}
                        placeholder="选择 Provider"
                        style={{ flex: 1, minWidth: 120 }}
                        onChange={(provider) => {
                          const item = providers.find((candidate) => candidate.provider === provider)
                          setPreviewProvider(provider)
                          setPreviewModel(item?.default_model || item?.models?.[0] || '')
                        }}
                        options={providers.map((provider) => ({
                          value: provider.provider,
                          label: `${provider.provider === 'mock' ? '本地演示' : provider.provider}${provider.available ? '' : '（未配置）'}`,
                          disabled: !provider.available,
                        }))}
                      />
                      {previewProvider && providers.find((provider) => provider.provider === previewProvider)?.is_mock && <Tag color="orange">演示模式</Tag>}
                    </Space>
                    {previewJob?.status === 'running' || previewJob?.status === 'queued' || previewJob?.status === 'previewing' ? <><Progress percent={previewJob.progress || 15} status="active" /><Text type="secondary">视频生成中，请稍候...</Text></> : previewUrl ? <video controls src={previewUrl} style={{ width: '100%', borderRadius: 8, background: '#111827' }} /> : <Empty image={<VideoCameraOutlined style={{ fontSize: 42, color: '#8aa4c8' }} />} description="尚未试生成" />}
                    {previewJob?.status === 'failed' && <Alert type="error" showIcon message="试生成失败" description={previewJob.error_message || '请检查模型配置后重试'} style={{ marginTop: 12 }} />}
                    {previewJob?.status === 'success' && <Alert type="success" showIcon message="试生成已加入素材库" description="可以在素材库的视频分类中查看、下载或重命名。" style={{ marginTop: 12 }} />}
                  </Card>
                </Col>
                <Col xs={24} lg={8}>
                  <Card size="small" title="发布范围">
                    <Radio.Group value={publishScope} onChange={(event) => setPublishScope(event.target.value)}>
                      <Space direction="vertical"><Radio value="personal">仅自己可见</Radio><Radio value="organization">当前企业可见</Radio></Space>
                    </Radio.Group>
                  </Card>
                </Col>
              </Row>
            )}
          </div>
        )}
      </main>

      <footer className="video-template-footer">
        <Space style={{ width: '100%', justifyContent: 'space-between' }}>
          <Text type="secondary">{draft ? `草稿：${draft.name}` : '先上传专业视频开始创建'}</Text>
          <Space>
            <Button onClick={goBack} disabled={currentStep <= 1}>上一步</Button>
            <Button type="primary" loading={processing || publishing} disabled={!canContinue} onClick={goNext} icon={currentStep === 5 && previewJob?.status === 'success' ? <CheckCircleOutlined /> : <ThunderboltOutlined />}>
              {currentStep === 0 ? '开始截取镜头' : currentStep === 1 ? '提取关键帧' : currentStep === 2 ? '进入 AI 提炼' : currentStep === 3 ? '生成模板配方' : currentStep === 4 ? '进入试生成与发布' : previewJob?.status === 'success' ? '发布模板' : '试生成视频'}
            </Button>
          </Space>
        </Space>
      </footer>
    </div>
  )
}
