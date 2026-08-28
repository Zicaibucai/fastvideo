import { describe, expect, it } from 'vitest'
import { render, screen } from '@testing-library/react'
import ReviewStateTag from './ReviewStateTag'
import { REVIEW_STATE_LABELS } from '../../hooks/useProjectPermissions'

describe('ReviewStateTag 审核状态转换展示', () => {
  it('draft 显示未提交审核', () => {
    render(<ReviewStateTag state="draft" />)
    expect(screen.getByText(REVIEW_STATE_LABELS.draft)).toBeInTheDocument()
  })

  it('in_review 显示审核中', () => {
    render(<ReviewStateTag state="in_review" />)
    expect(screen.getByText(REVIEW_STATE_LABELS.in_review)).toBeInTheDocument()
  })

  it('changes_requested 显示要求修改', () => {
    render(<ReviewStateTag state="changes_requested" />)
    expect(screen.getByText(REVIEW_STATE_LABELS.changes_requested)).toBeInTheDocument()
  })

  it('approved 显示已批准', () => {
    render(<ReviewStateTag state="approved" />)
    expect(screen.getByText(REVIEW_STATE_LABELS.approved)).toBeInTheDocument()
  })

  it('approved_but_changed 显示批准后已变更', () => {
    render(<ReviewStateTag state="approved_but_changed" />)
    expect(screen.getByText(REVIEW_STATE_LABELS.approved_but_changed)).toBeInTheDocument()
  })

  it('空状态回退为 draft', () => {
    render(<ReviewStateTag state={null} />)
    expect(screen.getByText(REVIEW_STATE_LABELS.draft)).toBeInTheDocument()
  })
})
