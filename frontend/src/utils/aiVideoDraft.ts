export type AiVideoDraft = {
  version?: number
  updatedAt?: string
  recipe?: Record<string, any> | null
  /** 只有从施工工作台确认应用后，V2 施工配方才参与快速生成。 */
  advancedEnabled?: boolean
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
}

const storageKey = (projectId: string) => `fastvideo:ai-video-draft:v2:${projectId}`

export const readAiVideoDraft = (projectId: string): AiVideoDraft | null => {
  if (!projectId || typeof window === 'undefined') return null
  try {
    const raw = window.localStorage.getItem(storageKey(projectId))
    if (!raw) return null
    const parsed = JSON.parse(raw)
    return parsed && typeof parsed === 'object' ? parsed as AiVideoDraft : null
  } catch {
    return null
  }
}

export const saveAiVideoDraft = (projectId: string, patch: AiVideoDraft) => {
  if (!projectId || typeof window === 'undefined') return
  const current = readAiVideoDraft(projectId) || {}
  window.localStorage.setItem(storageKey(projectId), JSON.stringify({
    ...current,
    ...patch,
    version: 2,
    updatedAt: new Date().toISOString(),
  }))
}
