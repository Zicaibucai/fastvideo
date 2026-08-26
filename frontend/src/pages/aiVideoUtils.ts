import type {
  VideoGenerationTemplate,
  VideoGenerationVersion,
} from '../api/types'
import { withAuthToken } from '../api/client'

export const DURATION_OPTIONS = [5, 8, 10, 15]
export const RATIO_OPTIONS = ['adaptive', '16:9', '9:16', '4:3', '3:4', '1:1', '21:9']
export const RESOLUTION_OPTIONS = ['480p', '720p', '1080p']

export type JsonRecord = Record<string, unknown>

export const normalizeResolution = (value: unknown, fallback = '720p') => {
  const normalized = String(value || '').trim().toLowerCase()
  return RESOLUTION_OPTIONS.includes(normalized) ? normalized : fallback
}

export const sanitizePromptResolution = (value: string) => {
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

export const PROVIDER_LABELS: Record<string, string> = {
  seedance: '即梦 Seedance',
  minimax: '历史视频通道',
  mock: '本地演示',
}

export const templateAssetUrl = (fileKey?: string) => (fileKey ? withAuthToken(`/files/${fileKey}`) : undefined)

export const templateMode = (template: VideoGenerationTemplate) => {
  const modes = template.applicable_modes || []
  if (modes.includes('first_last_frame_video')) return 'first_last_frame_video' as const
  if (modes.includes('multi_reference_video')) return 'multi_reference_video' as const
  return 'image_to_video' as const
}

export const isFlexibleReferenceTemplate = (template: VideoGenerationTemplate) =>
  (template.applicable_modes || []).includes('multi_reference_video')

export const templateSupportsMode = (template: VideoGenerationTemplate, mode: string) => {
  const modes = template.applicable_modes || []
  if (isFlexibleReferenceTemplate(template)) return true
  if (modes.includes(mode)) return true
  return mode === 'multi_reference_video' && modes.includes('image_to_video')
}

export const templateReferenceCount = (template: VideoGenerationTemplate) => {
  if (template.reference_frame_count && template.reference_frame_count > 0) return Math.min(9, template.reference_frame_count)
  const modes = template.applicable_modes || []
  if (modes.includes('multi_reference_video')) return 3
  if (modes.includes('first_last_frame_video')) return 2
  return 1
}

export const templatePrompt = (template: VideoGenerationTemplate) => {
  const recipePrompt = template.prompt_recipe?.prompt
  return typeof recipePrompt === 'string' && recipePrompt.trim()
    ? recipePrompt
    : template.default_positive_prompt || ''
}

export const isConstructionRecipe = (recipe: JsonRecord | null) => Boolean(
  recipe && (
    Number(recipe.recipe_version || 0) >= 2
    || recipe.construction_mode === 'construction_evolution'
    || recipe.project_facts
    || recipe.construction_unit
  ),
)

export const parsePromptMasterPayload = (data: JsonRecord | null | undefined) => {
  const source = data || {}
  const directPrompt = typeof source.prompt === 'string' ? source.prompt.trim() : ''
  let structured: JsonRecord | null = null
  const candidates = [directPrompt, typeof source.raw_prompt === 'string' ? source.raw_prompt.trim() : '']
  for (const candidate of candidates) {
    if (!candidate || !(/[{}]/.test(candidate))) continue
    const clean = candidate.replace(/^\s*```(?:json)?\s*/i, '').replace(/\s*```\s*$/i, '').trim()
    const start = clean.indexOf('{')
    const end = clean.lastIndexOf('}')
    if (start < 0 || end <= start) continue
    try {
      const parsed: unknown = JSON.parse(clean.slice(start, end + 1))
      if (parsed && typeof parsed === 'object' && !Array.isArray(parsed)) {
        structured = parsed as JsonRecord
        break
      }
    } catch {
      // 模型返回普通文本时继续使用原始 prompt。
    }
  }
  const recipeValue = source.recipe && typeof source.recipe === 'object'
    ? source.recipe
    : structured?.recipe && typeof structured.recipe === 'object'
      ? structured.recipe
      : null
  const recipe = recipeValue as JsonRecord | null
  return {
    prompt: String(structured?.prompt || directPrompt || '').trim(),
    negativePrompt: String(source.negative_prompt || structured?.negative_prompt || '').trim(),
    recipe,
    name: String(source.name || structured?.name || '').trim(),
    description: String(source.description || structured?.description || '').trim(),
  }
}

export const recipeDuration = (value: unknown, fallback = 5) => {
  const numbers = String(value ?? '').match(/\d+(?:\.\d+)?/g)?.map(Number) || []
  if (!numbers.length) return fallback
  const selected = numbers.length > 1 ? (numbers[0] + numbers[1]) / 2 : numbers[0]
  return Math.max(2, Math.min(15, Math.round(selected)))
}

export const expandRecipePrompt = (prompt: string, recipe: JsonRecord | null) => {
  if (!recipe) return prompt.trim()
  const parts = [prompt.trim()]
  const camera = recipe.camera
  if (camera && typeof camera === 'object') {
    const cameraRecord = camera as JsonRecord
    const fields = [
      cameraRecord.type ? `类型：${cameraRecord.type}` : '',
      cameraRecord.direction ? `方向：${cameraRecord.direction}` : '',
      cameraRecord.path ? `路径：${cameraRecord.path}` : '',
      cameraRecord.speed ? `速度：${cameraRecord.speed}` : '',
      cameraRecord.intensity ? `强度：${cameraRecord.intensity}` : '',
    ].filter(Boolean)
    if (fields.length) parts.push(`运镜设定：${fields.join('；')}`)
  } else if (camera) {
    parts.push(`运镜设定：${String(camera)}`)
  }
  if (Array.isArray(recipe.timeline) && recipe.timeline.length) {
    const timeline = recipe.timeline
      .map((item) => {
        const entry = item as JsonRecord
        return `${entry.from ?? 0}%-${entry.to ?? 100}%：${entry.instruction || entry.description || ''}`
      })
      .filter(Boolean)
      .join('；')
    if (timeline) parts.push(`时间轴：${timeline}`)
  } else if (recipe.timeline) {
    parts.push(`时间轴：${String(recipe.timeline)}`)
  }
  if (Array.isArray(recipe.reference_timing_seconds) && recipe.reference_timing_seconds.length) {
    const timing = recipe.reference_timing_seconds
      .map((value, index) => {
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
  const list = (value: unknown) => Array.isArray(value) ? value.filter(Boolean).join('；') : value ? String(value) : ''
  if (list(recipe.preserve)) parts.push(`建筑保持项（必须锁定）：${list(recipe.preserve)}`)
  if (list(recipe.allow_change)) parts.push(`允许变化项（仅限这些变化）：${list(recipe.allow_change)}`)
  return parts.filter(Boolean).join('。')
}

export const versionDisplayName = (version: VideoGenerationVersion) =>
  version.name?.trim() || `AI视频 V${version.version_number}`

export const versionDownloadName = (version: VideoGenerationVersion) => {
  const name = versionDisplayName(version)
  return /\.[a-z0-9]{2,8}$/i.test(name) ? name : `${name}.mp4`
}

export const formatImageDimensions = (width?: number, height?: number) => (
  Number.isFinite(width) && Number(width) > 0 && Number.isFinite(height) && Number(height) > 0
    ? `${width} × ${height}`
    : ''
)

export const TEMPLATE_PREVIEWS: Record<string, { video: string; first: string; last?: string }> = {
  '建筑平移': { video: '/templates/01/preview.webm', first: '/templates/01/first.jpg' },
  '建筑鸟瞰环绕': { video: '/templates/02/preview.webm', first: '/templates/02/first.jpg' },
  '建筑从整体到局部': { video: '/templates/03/preview.webm', first: '/templates/03/first.jpg' },
  '建筑从室外到室内': { video: '/templates/04/preview.webm', first: '/templates/04/first.jpg' },
  '希区柯克推进': { video: '/templates/05/preview.webm', first: '/templates/05/first.jpg' },
  '中心环绕': { video: '/templates/06/preview.webm', first: '/templates/06/first.jpg' },
  '起重机': { video: '/templates/07/preview.webm', first: '/templates/07/first.jpg' },
  '超级拉远': { video: '/templates/08/preview.webm', first: '/templates/08/first.jpg' },
  '延时摄影': { video: '/templates/09/preview.webm', first: '/templates/09/first.jpg' },
  '俯瞰➕环绕': { video: '/templates/10/preview.webm', first: '/templates/10/first.jpg' },
  '推进+仰拍': { video: '/templates/11/preview.webm', first: '/templates/11/first.jpg' },
  '拉远': { video: '/templates/12/preview.webm', first: '/templates/12/first.jpg' },
  '建筑生长动画': { video: '/templates/13/preview.webm', first: '/templates/13/first.jpg', last: '/templates/13/last.jpg' },
  '城市生长动画': { video: '/templates/14/preview.webm', first: '/templates/14/first.jpg', last: '/templates/14/last.jpg' },
  '建筑像火箭一样升空': { video: '/templates/15/preview.webm', first: '/templates/15/first.jpg', last: '/templates/15/last.jpg' },
  '线稿转实景图': { video: '/templates/16/preview.webm', first: '/templates/16/first.jpg', last: '/templates/16/last.jpg' },
  '根据这张城市公园中的多层图书馆的建筑俯视图，生成对应的低空平视规划实景照片': { video: '/templates/17/preview.webm', first: '/templates/17/first.jpg', last: '/templates/17/last.jpg' },
  '视角转换': { video: '/templates/18/preview.webm', first: '/templates/18/first.jpg', last: '/templates/18/last.jpg' },
  '建筑工人施工将建筑的立面材质改为红砖': { video: '/templates/19/preview.webm', first: '/templates/19/first.jpg', last: '/templates/19/last.jpg' },
  '天气转变为大雾天气，固定视角，延时摄影': { video: '/templates/20/preview.webm', first: '/templates/20/first.jpg', last: '/templates/20/last.jpg' },
  '从白天到日落，固定视角，延时摄影': { video: '/templates/21/preview.webm', first: '/templates/21/first.jpg', last: '/templates/21/last.jpg' },
  '将图片中的氛围切换到夜晚，突出建筑内的灯光照明': { video: '/templates/22/preview.webm', first: '/templates/22/first.jpg', last: '/templates/22/last.jpg' },
  '图片中的天气切换为冬天，白雪覆盖建筑地面树木': { video: '/templates/23/preview.webm', first: '/templates/23/first.jpg', last: '/templates/23/last.jpg' },
  '变成微缩景观': { video: '/templates/24/preview.webm', first: '/templates/24/first.jpg', last: '/templates/24/last.jpg' },
  '白纸平整的置于桌面上，镜头快速由远景推近，紧接着环绕纸张进行旋转，以纸张为中心，线条开始如灵动的精灵般浮现交织，色彩逐渐晕染开来，随着镜头缓缓上升，画面中的线条与色彩不断汇聚、组合。建筑得轮廓逐渐清晰，最终画面定格在建筑图，这座宏伟的建筑完美呈现，仿佛从这张白纸之上拔地而起': { video: '/templates/25/preview.webm', first: '/templates/25/first.jpg', last: '/templates/25/last.jpg' },
  '变成微缩模型': { video: '/templates/26/preview.webm', first: '/templates/26/first.jpg', last: '/templates/26/last.jpg' },
  '街道翻新': { video: '/templates/27/preview.webm', first: '/templates/27/first.jpg', last: '/templates/27/last.jpg' },
  '根据手稿生成建筑': { video: '/templates/28/preview.webm', first: '/templates/28/first.jpg', last: '/templates/28/last.jpg' },
  '色彩从中心晕开': { video: '/templates/29/preview.webm', first: '/templates/29/first.jpg', last: '/templates/29/last.jpg' },
  '对建筑进行设计标注': { video: '/templates/30/preview.webm', first: '/templates/30/first.jpg', last: '/templates/30/last.jpg' },
  '生成建筑爆炸图': { video: '/templates/31/preview.webm', first: '/templates/31/first.jpg', last: '/templates/31/last.jpg' },
  '两名女士走到沙发上聊天': { video: '/templates/32/preview.webm', first: '/templates/32/first.jpg', last: '/templates/32/last.jpg' },
  '建筑工人对房屋进行翻新装修': { video: '/templates/33/preview.webm', first: '/templates/33/first.jpg', last: '/templates/33/last.jpg' },
  '生成建筑轴测模型': { video: '/templates/34/preview.webm', first: '/templates/34/first.jpg', last: '/templates/34/last.jpg' },
  '卡通人物走到沙发上交流': { video: '/templates/35/preview.webm', first: '/templates/35/first.jpg', last: '/templates/35/last.jpg' },
  '两个卡通人物走到咖啡厅门前喝咖啡': { video: '/templates/36/preview.webm', first: '/templates/36/first.jpg', last: '/templates/36/last.jpg' },
  '创建这座建筑的剖面图，一侧显示完整的外部结构，另一侧显示内部的结构以及装修细节。保持比例准确，细节逼真。': { video: '/templates/37/preview.webm', first: '/templates/37/first.jpg', last: '/templates/37/last.jpg' },
  '绘制一个 A6 折叠卡：打开时它会展示一个完整的 3D 球形小屋，里面有一座微型的纸花园和盆景树。': { video: '/templates/38/preview.webm', first: '/templates/38/first.jpg', last: '/templates/38/last.jpg' },
  '把这张建筑线稿图转成实景照片，要求摄影质感，真实的光影效果。阴天乌云密布，建筑里透出灯光，建筑前有零星的行人。保持画面结构不变。': { video: '/templates/39/preview.webm', first: '/templates/39/first.jpg', last: '/templates/39/last.jpg' },
  '将图片变真实': { video: '/templates/40/preview.webm', first: '/templates/40/first.jpg', last: '/templates/40/last.jpg' },
  '从红色圆圈沿箭头方向画出真实世界的视角': { video: '/templates/41/preview.webm', first: '/templates/41/first.jpg', last: '/templates/41/last.jpg' },
  '装修工人对房间进行布置': { video: '/templates/42/preview.webm', first: '/templates/42/first.jpg', last: '/templates/42/last.jpg' },
}
