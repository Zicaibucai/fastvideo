import { Tag } from 'antd'
import { FACT_STATUS_MAP } from '../../features/storyboard/constants'

/** 统一显示事实校验状态，避免编辑器和预览区各自维护一套映射。 */
export default function FactTag({ status }: { status?: string }) {
  if (!status) return null
  const item = FACT_STATUS_MAP[status] || { label: status, color: 'default' }
  return <Tag color={item.color}>{item.label}</Tag>
}
