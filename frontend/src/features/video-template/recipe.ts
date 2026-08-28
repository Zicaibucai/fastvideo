import { withAuthToken } from '../../api/client'

export type TemplateGenerationMode = 'image_to_video' | 'first_last_frame_video' | 'multi_reference_video'

export const MAX_REFERENCE_IMAGES = 9

export const TEMPLATE_MODE_LABELS: Record<TemplateGenerationMode, string> = {
  image_to_video: '单图生成',
  first_last_frame_video: '首尾帧生成',
  multi_reference_video: '多图生成',
}

export const fileUrl = (key?: string) => {
  if (!key) return ''
  return withAuthToken(key.startsWith('/') || /^https?:\/\//i.test(key) ? key : `/files/${key}`)
}

export const templateDraftStorageKey = (projectId: string) => `fastvideo:template-draft:${projectId}`

export const recipeText = (recipe: Record<string, any> | undefined, key: string, fallback = '') => {
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

export const recipeItems = (value: any, fallback: string[] = []) => {
  if (Array.isArray(value)) return value.map((item) => String(item).trim()).filter(Boolean)
  if (typeof value === 'string' && value.trim()) return value.split(/[；;、,，\n]+/).map((item) => item.trim()).filter(Boolean)
  return fallback
}

export const recipeTimeline = (value: any) => {
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
  if (typeof value === 'string' && value.trim()) return [
    { from: 0, to: 20, instruction: '建立首帧构图，锁定建筑主体与空间关系' },
    { from: 20, to: 80, instruction: value.trim() },
    { from: 80, to: 100, instruction: '平稳过渡至尾帧并减速定格，保持结构连续' },
  ]
  return [
    { from: 0, to: 20, instruction: '建立首帧构图，镜头开始缓慢移动' },
    { from: 20, to: 80, instruction: '保持建筑主体稳定，呈现自然空间变化' },
    { from: 80, to: 100, instruction: '平稳到达尾帧构图并减速定格' },
  ]
}

export const recipeCamera = (value: any) => {
  if (value && typeof value === 'object') return value
  return { type: String(value || '稳定运镜'), speed: '平稳', direction: '-', path: '-', intensity: '低' }
}
