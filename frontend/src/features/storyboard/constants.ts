export const SECTION_OPTIONS = ['片头', '项目概况', '施工部署', '项目重难点', '施工方案', '保证措施', '片尾']

export const VISUAL_TYPES = [
  { label: '标题', value: 'title' },
  { label: '模型图片', value: 'model_image' },
  { label: '现场照片', value: 'site_photo' },
  { label: 'AI生成图片', value: 'generated_image' },
  { label: 'AI生成视频', value: 'generated_video' },
  { label: 'BIM动画', value: 'bim_animation' },
  { label: '信息图表', value: 'infographic' },
]

export const FACT_STATUS_MAP: Record<string, { label: string; color: string }> = {
  verified: { label: '已核实', color: 'success' },
  partial: { label: '部分核实', color: 'warning' },
  unverified: { label: '未验证', color: 'error' },
  conflict: { label: '冲突', color: 'volcano' },
}

export function formatTimecode(seconds: number) {
  const safeSeconds = Math.max(0, Math.floor(seconds || 0))
  const minutes = Math.floor(safeSeconds / 60)
  const remaining = safeSeconds % 60
  return `${minutes}:${String(remaining).padStart(2, '0')}`
}

export function splitPreviewParagraphs(text: string) {
  const sentences = (text || '').split(/(?<=[。！？；])/).map((sentence) => sentence.trim()).filter(Boolean)
  if (sentences.length === 0 && text.trim()) return [text.trim()]
  const paragraphs: string[] = []
  let current = ''
  for (const sentence of sentences) {
    const next = current ? `${current}${sentence}` : sentence
    if (current && next.length > 110) {
      paragraphs.push(current)
      current = sentence
    } else current = next
  }
  if (current) paragraphs.push(current)
  return paragraphs
}
