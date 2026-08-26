import { useEffect, useMemo, useState } from 'react'
import { App, Modal } from 'antd'
import { SafetyOutlined } from '@ant-design/icons'
import { useLocation, useNavigate, useParams } from 'react-router-dom'
import { ConstructionWorkbenchContent } from '../components/ConstructionWorkbenchModal'
import { videoGenApi } from '../api'
import type { ReferenceImage, VideoGenerationJob } from '../api/types'
import { readAiVideoDraft, saveAiVideoDraft, type AiVideoDraft } from '../utils/aiVideoDraft'
import { threeZoneSlabPromptExample, threeZoneSlabRecipeExample } from '../data/constructionRecipeExamples'

type Recipe = Record<string, any>

type WorkbenchState = {
  advancedWorkbench?: boolean
  recipe?: Recipe | null
  prompt?: string
  negativePrompt?: string
  selectedProvider?: string
  modelName?: string
  duration?: number
  firstFrameId?: string
  lastFrameId?: string
  referenceAssetIds?: string[]
  selectedTemplateId?: string
  generationMode?: 'image_to_video' | 'first_last_frame_video' | 'multi_reference_video'
  aspectRatio?: string
  resolution?: string
  generateAudio?: boolean
  constraintsEnabled?: boolean
  seedLock?: boolean
  seed?: number | null
  submittedJob?: VideoGenerationJob
  advancedEnabled?: boolean
}

const defaultRecipe: Recipe = {
  recipe_version: 2,
  construction_mode: 'construction_evolution',
  project_facts: { structure_type: '', current_stage: '', target_stage: '', fact_sources: [] },
  construction_unit: { wbs_code: '', work_item: '', work_zone: '', zone_mappings: [], objects: [], prerequisites: [], completion_state: [] },
  state_transition: { start_state: '', end_state: '', allowed_changes: [], forbidden_jumps: [] },
  spatial_anchors: [],
  temporary_works: { required: [], forbidden: [] },
  safety_constraints: [],
  quality_constraints: [],
  acceptance_checks: [],
}

const inferZoneMappings = (text: string, recipe: Recipe): Recipe => {
  const currentUnit = recipe.construction_unit || {}
  if (Array.isArray(currentUnit.zone_mappings) && currentUnit.zone_mappings.length) return recipe
  const match = String(text || '').match(/分区定位\s*[：:]\s*([\s\S]*?)(?=。\s*(?:三个分区|工程状态|状态|施工时间轴|摄影时间轴)|$)/)
  const mappings = match?.[1]
    ? match[1]
    .split(/[；;]/)
    .map((item) => item.trim())
    .filter((item) => /^(?:①|②|③)区/.test(item))
    : []
  const fallbackMappings = /①/.test(String(currentUnit.work_zone || text)) && /②/.test(String(currentUnit.work_zone || text)) && /③/.test(String(currentUnit.work_zone || text))
    ? [
        '①区=画面左侧及上侧的外围裙房梁板范围',
        '②区=画面中央主楼核心周边梁板范围',
        '③区=画面右下侧、尾帧最后补齐的剩余梁板范围',
      ]
    : []
  const nextMappings = mappings.length ? mappings : fallbackMappings
  return nextMappings.length
    ? { ...recipe, construction_unit: { ...currentUnit, zone_mappings: nextMappings } }
    : recipe
}

export default function ConstructionWorkbenchPage() {
  const { projectId = '' } = useParams()
  const navigate = useNavigate()
  const location = useLocation()
  const { message } = App.useApp()
  const incoming = (location.state || {}) as WorkbenchState
  const [initialDraft] = useState<WorkbenchState & AiVideoDraft>(() => {
    const saved = readAiVideoDraft(projectId) || {}
    const initialPrompt = incoming.prompt || saved.prompt || ''
    const incomingRecipe = incoming.recipe || null
    const savedRecipe = saved.recipe || null
    // 浏览器 history 里的 advancedState 可能是进入页面时的旧快照；
    // 如果自动精简已经写入草稿，优先采用没有旧人工终稿的本地草稿，
    // 避免刷新后又把 1300+ 字的旧 provider_prompt_override 带回来。
    const incomingOverride = String(incomingRecipe?.provider_prompt_override || '').trim()
    const savedOverride = String(savedRecipe?.provider_prompt_override || '').trim()
    const initialRecipe = incomingOverride && savedRecipe && !savedOverride
      ? savedRecipe
      : incomingRecipe || savedRecipe || defaultRecipe
    return {
      ...saved,
      ...incoming,
      prompt: initialPrompt,
      recipe: inferZoneMappings(initialPrompt, initialRecipe),
    }
  })
  const [recipe, setRecipe] = useState<Recipe | null>(initialDraft.recipe || defaultRecipe)
  const [prompt, setPrompt] = useState(initialDraft.prompt || '')
  const [negativePrompt] = useState(initialDraft.negativePrompt || '')
  const [provider] = useState('seedance')
  const [modelName, setModelName] = useState(initialDraft.modelName || '')
  const [duration, setDuration] = useState(initialDraft.duration || 5)
  const [firstFrameId] = useState(initialDraft.firstFrameId || '')
  const [lastFrameId] = useState(initialDraft.lastFrameId || '')
  const [referenceAssetIds] = useState<string[]>(initialDraft.referenceAssetIds || [])
  const [selectedTemplateId] = useState(initialDraft.selectedTemplateId || '')
  const [referenceImages, setReferenceImages] = useState<ReferenceImage[]>([])
  const [compiledPrompt, setCompiledPrompt] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const generationMode = initialDraft.generationMode || 'first_last_frame_video'
  const aspectRatio = initialDraft.aspectRatio || 'adaptive'
  const requestedResolution = String(initialDraft.resolution || '').trim().toLowerCase()
  const resolution = ['480p', '720p', '1080p'].includes(requestedResolution) ? requestedResolution : '720p'
  const generateAudio = initialDraft.generateAudio ?? false
  const constraintsEnabled = initialDraft.constraintsEnabled ?? true
  const seedLock = initialDraft.seedLock ?? false
  const seed = initialDraft.seed ?? null

  useEffect(() => {
    videoGenApi.referenceImages(projectId).then((response) => setReferenceImages(response.data)).catch(() => {})
    videoGenApi.providers(projectId).then((response) => {
      const active = response.data.find((item: any) => item.provider === 'seedance')
      if (active) {
        if (!modelName) setModelName(active.default_model || active.models?.[0] || '')
      }
    }).catch(() => {})
  }, [projectId])

  useEffect(() => {
    if (!projectId) return
    const timer = window.setTimeout(() => {
      videoGenApi.compilePrompt(projectId, {
        positive_prompt: prompt,
        negative_prompt: negativePrompt || null,
        prompt_recipe: recipe,
        template_id: selectedTemplateId || null,
        constraints_enabled: true,
        resolution,
      }).then((response) => {
        setCompiledPrompt(response.data.provider_prompt || response.data.positive_prompt || '')
      }).catch(() => setCompiledPrompt(''))
    }, 250)
    return () => window.clearTimeout(timer)
  }, [projectId, prompt, negativePrompt, recipe, selectedTemplateId, resolution])

  useEffect(() => {
    const timer = window.setTimeout(() => saveAiVideoDraft(projectId, {
      recipe,
      prompt,
      negativePrompt,
      selectedProvider: 'seedance',
      modelName,
      duration,
      firstFrameId,
      lastFrameId,
      referenceAssetIds,
      selectedTemplateId,
    }), 180)
    return () => window.clearTimeout(timer)
  }, [projectId, recipe, prompt, negativePrompt, modelName, duration, firstFrameId, lastFrameId, referenceAssetIds, selectedTemplateId])

  const firstFrame = useMemo(() => referenceImages.find((image) => image.id === firstFrameId) || null, [referenceImages, firstFrameId])
  const lastFrame = useMemo(() => referenceImages.find((image) => image.id === lastFrameId) || null, [referenceImages, lastFrameId])
  const selectedReferenceImages = useMemo(
    () => referenceAssetIds.map((id) => referenceImages.find((image) => image.id === id)).filter((image): image is ReferenceImage => Boolean(image)),
    [referenceAssetIds, referenceImages],
  )

  const backState = {
    ...initialDraft,
    ...incoming,
    recipe,
    prompt,
    negativePrompt,
    selectedProvider: provider,
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

  const goBack = () => {
    const quickState = { ...backState, advancedEnabled: false }
    saveAiVideoDraft(projectId, quickState)
    navigate(`/project/${projectId}/ai-video`, { state: quickState })
  }

  const applyAndGenerate = async (structureConflictConfirmed = false) => {
    if (!firstFrameId || !firstFrame) {
      message.warning('首帧未选择或素材已不可用，请先返回快速生成重新选择')
      return
    }
    if (generationMode === 'first_last_frame_video' && (!lastFrameId || !lastFrame)) {
      message.warning('首尾帧模式必须同时选择有效的首帧和尾帧')
      return
    }
    if (generationMode === 'multi_reference_video' && selectedReferenceImages.length < 2) {
      message.warning('多参考图模式至少需要两张有效参考图')
      return
    }
    const effectivePrompt = String(recipe?.provider_prompt_override || compiledPrompt || prompt || '').trim()
    if (!effectivePrompt) {
      message.warning('最终 Seedance 投喂内容为空，请先完成提示词配置')
      return
    }

    if (!structureConflictConfirmed) {
      try {
        const check = await videoGenApi.constraintCheck(projectId, effectivePrompt, recipe)
        if (check.data.blocked) {
          Modal.confirm({
            title: '检测到可能改变工程结构的描述',
            icon: <SafetyOutlined />,
            content: `系统识别到：${check.data.conflicts.join('、')}。如果这是已声明的施工演进，请确认后继续。`,
            okText: '确认并开始生成',
            cancelText: '返回修改',
            okButtonProps: { danger: true },
            onOk: () => applyAndGenerate(true),
          })
          return
        }
      } catch {
        // 正式任务接口仍会执行同一套后端校验。
      }
    }

    setSubmitting(true)
    try {
      const appliedState = { ...backState, advancedEnabled: true }
      saveAiVideoDraft(projectId, appliedState)
      const response = await videoGenApi.createTask(projectId, {
        generation_mode: generationMode,
        first_frame_asset_id: firstFrameId,
        last_frame_asset_id: generationMode === 'first_last_frame_video' ? lastFrameId : undefined,
        reference_asset_ids: generationMode === 'multi_reference_video' ? referenceAssetIds : [],
        template_id: selectedTemplateId || null,
        prompt_recipe: recipe || undefined,
        provider: 'seedance',
        model_name: modelName || undefined,
        positive_prompt: prompt,
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
      message.success('Seedance 视频生成任务已提交')
      navigate(`/project/${projectId}/ai-video`, {
        state: { ...appliedState, submittedJob: response.data },
      })
    } catch {
      setSubmitting(false)
      // 请求拦截器会显示后端给出的具体错误。
    }
  }

  const loadThreeZoneExample = () => {
    const exampleRecipe = JSON.parse(JSON.stringify(threeZoneSlabRecipeExample))
    setRecipe(exampleRecipe)
    setPrompt(threeZoneSlabPromptExample)
    setDuration(15)
    // 示例恢复是一次完整的数据操作，立即落盘，避免用户加载后立刻刷新时被旧草稿覆盖。
    saveAiVideoDraft(projectId, {
      recipe: exampleRecipe,
      prompt: threeZoneSlabPromptExample,
      duration: 15,
    })
  }

  return (
    <div style={{ minHeight: 'calc(100vh - 68px)', margin: '-28px -32px -40px', background: '#f4f6f9' }}>
      <ConstructionWorkbenchContent
        open
        onClose={goBack}
        onApply={applyAndGenerate}
        applyLoading={submitting}
        onLoadExample={loadThreeZoneExample}
        recipe={recipe}
        onChange={setRecipe}
        prompt={prompt}
        compiledPrompt={compiledPrompt}
        negativePrompt={negativePrompt}
        provider={provider}
        modelName={modelName}
        duration={duration}
        generationMode={generationMode}
        firstFrame={firstFrame}
        lastFrame={lastFrame || selectedReferenceImages[selectedReferenceImages.length - 1]}
        referenceImages={selectedReferenceImages}
      />
    </div>
  )
}
