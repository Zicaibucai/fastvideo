import { useCallback, useEffect, useMemo, useState } from 'react'
import {
  Alert,
  App,
  Button,
  Card,
  Col,
  Collapse,
  Divider,
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
  Tag,
  Typography,
  Upload,
} from 'antd'
import {
  ArrowRightOutlined,
  CheckCircleOutlined,
  CheckOutlined,
  DeleteOutlined,
  EditOutlined,
  LockOutlined,
  PlayCircleOutlined,
  ReloadOutlined,
  SafetyOutlined,
  ThunderboltOutlined,
  UnlockOutlined,
} from '@ant-design/icons'
import { useLocation, useNavigate, useParams } from 'react-router-dom'
import AiVideoVersionDrawer from '../components/ai-video/AiVideoVersionDrawer'
import {
  assetApi,
  videoGenApi,
} from '../api'
import type {
  ReferenceImage,
  VideoGenerationJob,
  VideoGenerationTemplate,
  VideoGenerationVersion,
} from '../api/types'
import { readAiVideoDraft, saveAiVideoDraft } from '../utils/aiVideoDraft'
import {
  DURATION_OPTIONS,
  PROVIDER_LABELS,
  RATIO_OPTIONS,
  RESOLUTION_OPTIONS,
  expandRecipePrompt,
  formatImageDimensions,
  isConstructionRecipe,
  isFlexibleReferenceTemplate,
  normalizeResolution,
  parsePromptMasterPayload,
  recipeDuration,
  sanitizePromptResolution,
  templateMode,
  templatePrompt,
  templateReferenceCount,
  templateSupportsMode,
  versionDisplayName,
} from './aiVideoUtils'
import { useAiVideoData } from '../hooks/useAiVideoData'
import FrameSlot from '../components/ai-video/FrameSlot'
import AiVideoTemplateLibrary from '../components/ai-video/AiVideoTemplateLibrary'
import { modelButtonActive, modelButtonBase } from '../features/ai-video/styles'

const { Title, Text, Paragraph } = Typography




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
  const [selectedProvider, setSelectedProvider] = useState('seedance')

  const [submitting, setSubmitting] = useState(false)
  const [masterLoading, setMasterLoading] = useState(false)

  const onTaskComplete = useCallback((job: VideoGenerationJob) => {
    setSubmitting(false)
    if (job.status === 'success') {
      message.success(job.asset_status === 'ready' ? '视频生成完成，已写入素材库' : '视频生成完成')
    } else if (job.status === 'failed') {
      message.error(job.error_message || '视频生成失败，可点击重试')
    }
  }, [message])

  const {
    activeJob,
    activeJobId,
    providerCaps,
    providers,
    refImages,
    templates,
    versions,
    refresh: fetchAll,
    setActiveJob,
    setActiveJobId,
  } = useAiVideoData({ projectId, selectedProvider, onTaskComplete })

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


  const currentProvider = useMemo(
    () => providers.find((p) => p.provider === selectedProvider) || null,
    [providers, selectedProvider],
  )

  useEffect(() => {
    const provider = providers.find((item) => item.provider === selectedProvider)
    if (!provider) return
    setModelName((current) => current || provider.default_model || provider.models?.[0] || '')
  }, [providers, selectedProvider])

  const handleProviderChange = (provider: string) => {
    const p = providers.find((x) => x.provider === provider)
    setSelectedProvider(provider)
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
      void fetchAll()
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

      <AiVideoTemplateLibrary
        projectId={projectId}
        navigate={navigate}
        openAdvancedWorkbench={openAdvancedWorkbench}
        setDrawerOpen={setDrawerOpen}
        activeTab={activeTab}
        setActiveTab={setActiveTab}
        templateScopeFilter={templateScopeFilter}
        setTemplateScopeFilter={setTemplateScopeFilter}
        displayTemplates={displayTemplates}
        generationMode={generationMode}
        selectedTemplateId={selectedTemplateId}
        handleSelectTemplate={handleSelectTemplate}
        openTemplateApply={openTemplateApply}
        deletingTemplateId={deletingTemplateId}
        handleDeleteTemplate={handleDeleteTemplate}
        templateToApply={templateToApply}
        templateApplyOpen={templateApplyOpen}
        setTemplateApplyOpen={setTemplateApplyOpen}
        confirmTemplateApply={confirmTemplateApply}
        templateApplyMode={templateApplyMode}
        usingOriginalTemplateFrames={usingOriginalTemplateFrames}
        originalTemplateReferenceIds={originalTemplateReferenceIds}
        setApplyReferenceIds={setApplyReferenceIds}
        refImages={refImages}
        applyReferenceIds={applyReferenceIds}
        setApplyFirstFrameId={setApplyFirstFrameId}
        applyFirstFrameId={applyFirstFrameId}
        setApplyLastFrameId={setApplyLastFrameId}
        applyLastFrameId={applyLastFrameId}
        applySubject={applySubject}
        setApplySubject={setApplySubject}
        applyScene={applyScene}
        setApplyScene={setApplyScene}
      />

      <AiVideoVersionDrawer
        drawerOpen={drawerOpen}
        setDrawerOpen={setDrawerOpen}
        versions={versions}
        openRenameVersion={openRenameVersion}
        handleSelectVersion={handleSelectVersion}
        handleDeleteVersion={handleDeleteVersion}
      />

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
