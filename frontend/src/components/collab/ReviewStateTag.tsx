import { Tag, Tooltip } from 'antd'
import { REVIEW_STATE_COLORS, REVIEW_STATE_LABELS } from '../../hooks/useProjectPermissions'

/** 审核状态标签：draft / in_review / changes_requested / approved / approved_but_changed */
export default function ReviewStateTag({ state }: { state?: string | null }) {
  const value = state || 'draft'
  const color = REVIEW_STATE_COLORS[value] ?? 'default'
  const label = REVIEW_STATE_LABELS[value] ?? value
  if (value === 'approved_but_changed') {
    return (
      <Tooltip title="内容在批准后被修改，原批准已失效，需要重新提交审核">
        <Tag color={color}>{label}</Tag>
      </Tooltip>
    )
  }
  return <Tag color={color}>{label}</Tag>
}
