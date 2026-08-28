import { useCallback, useEffect, useState } from 'react'
import {
  Alert,
  Button,
  Descriptions,
  Empty,
  Input,
  List,
  Modal,
  Space,
  Tag,
  Typography,
} from 'antd'
import { CheckOutlined, CloseOutlined, DiffOutlined, SendOutlined } from '@ant-design/icons'
import { collabApi } from '../../api'
import type { CollabTargetType, ReviewRequest } from '../../api/types'
import { useProjectPermissions } from '../../hooks/useProjectPermissions'
import ReviewStateTag from './ReviewStateTag'
import MemberSelect from './MemberSelect'

const { Text, Paragraph } = Typography
const { TextArea } = Input

/**
 * 通用审核面板：当前状态 + 提交/批准/要求修改操作 + 历史记录 + 快照差异。
 * 用于工程信息、分镜文稿、视频工程等可审核对象。
 */
export default function ReviewPanel({
  projectId,
  targetType,
  targetId,
  currentState,
  onChanged,
}: {
  projectId: string
  targetType: CollabTargetType
  targetId?: string
  /** 外层已知的派生状态（可选，用于即时展示） */
  currentState?: string
  onChanged?: () => void
}) {
  const { has } = useProjectPermissions()
  const [reviews, setReviews] = useState<ReviewRequest[]>([])
  const [loading, setLoading] = useState(false)
  const [submitOpen, setSubmitOpen] = useState(false)
  const [note, setNote] = useState('')
  const [reviewerId, setReviewerId] = useState<string | undefined>()
  const [decideFor, setDecideFor] = useState<ReviewRequest | null>(null)
  const [decision, setDecision] = useState<'approved' | 'changes_requested'>('approved')
  const [decideComment, setDecideComment] = useState('')
  const [overrideReason, setOverrideReason] = useState('')
  const [diffFor, setDiffFor] = useState<ReviewRequest | null>(null)
  const [diffData, setDiffData] = useState<{ snapshot?: unknown; current?: unknown }>({})

  const canSubmit = has('review.submit')
  const canDecide = has('review.decide')
  const isOwner = has('admin.override')

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const resp = await collabApi.reviews(projectId, { target_type: targetType })
      const filtered = targetId
        ? resp.data.filter((r) => r.target_id === targetId)
        : resp.data.filter((r) => !r.target_id)
      setReviews(filtered)
    } catch {
      setReviews([])
    } finally {
      setLoading(false)
    }
  }, [projectId, targetType, targetId])

  useEffect(() => {
    void load()
  }, [load])

  const latest = reviews[0]
  const state = latest?.current_state || currentState || 'draft'

  const submit = async () => {
    await collabApi.submitReview(projectId, {
      target_type: targetType,
      target_id: targetId,
      note: note || undefined,
      assigned_reviewer_id: reviewerId,
    })
    setSubmitOpen(false)
    setNote('')
    setReviewerId(undefined)
    await load()
    onChanged?.()
  }

  const decide = async () => {
    if (!decideFor) return
    await collabApi.decideReview(projectId, decideFor.id, {
      decision,
      comment: decideComment || undefined,
      override_reason: overrideReason || undefined,
    })
    setDecideFor(null)
    setDecideComment('')
    setOverrideReason('')
    await load()
    onChanged?.()
  }

  const cancel = async (request: ReviewRequest) => {
    await collabApi.cancelReview(projectId, request.id)
    await load()
    onChanged?.()
  }

  const showDiff = async (request: ReviewRequest) => {
    const resp = await collabApi.reviewDetail(projectId, request.id)
    setDiffData({ snapshot: resp.data.snapshot, current: resp.data.current_snapshot })
    setDiffFor(request)
  }

  return (
    <div>
      <Space direction="vertical" style={{ width: '100%' }} size={8}>
        <Space>
          <Text strong>审核状态：</Text>
          <ReviewStateTag state={state} />
        </Space>
        {state === 'approved_but_changed' && (
          <Alert
            type="error"
            showIcon
            message="内容在批准后被修改，原批准已失效，请重新提交审核"
          />
        )}
        <Space wrap>
          {canSubmit && (
            <Button type="primary" icon={<SendOutlined />} onClick={() => setSubmitOpen(true)}>
              {state === 'draft' ? '提交审核' : '重新提交审核'}
            </Button>
          )}
          {!canSubmit && !canDecide && (
            <Text type="secondary">当前角色可查看审核状态，但不能提交或决定</Text>
          )}
        </Space>
      </Space>

      <List
        style={{ marginTop: 16 }}
        loading={loading}
        dataSource={reviews}
        locale={{ emptyText: <Empty description="暂无审核记录" /> }}
        renderItem={(request) => (
          <div
            key={request.id}
            style={{ padding: '8px 12px', marginBottom: 8, border: '1px solid #f0f0f0', borderRadius: 8 }}
          >
            <Space size={8} wrap>
              <ReviewStateTag state={request.current_state || request.status} />
              <Text type="secondary" style={{ fontSize: 12 }}>
                {request.submitted_by_name || '成员'} 提交于{' '}
                {new Date(request.submitted_at).toLocaleString('zh-CN')}
              </Text>
              <Text type="secondary" style={{ fontSize: 12 }}>
                版本 r{request.target_revision}
              </Text>
            </Space>
            {request.note && <Paragraph style={{ margin: '4px 0' }}>{request.note}</Paragraph>}
            {request.decisions.map((d) => (
              <div key={d.id} style={{ fontSize: 12, color: '#666', marginTop: 4 }}>
                <Tag color={d.decision === 'approved' ? 'green' : 'orange'}>
                  {d.decision === 'approved' ? '批准' : d.decision === 'changes_requested' ? '要求修改' : '驳回'}
                </Tag>
                {d.reviewer_name}：{d.comment || '（无说明）'}
                {d.is_override && <Tag color="purple" style={{ marginLeft: 4 }}>管理覆盖</Tag>}
              </div>
            ))}
            <Space size={8} style={{ marginTop: 4 }}>
              <Button size="small" type="link" icon={<DiffOutlined />} onClick={() => void showDiff(request)}>
                快照对比
              </Button>
              {request.status === 'pending' && (canDecide || (isOwner && request.submitted_by)) && (
                <>
                  <Button
                    size="small"
                    type="link"
                    icon={<CheckOutlined />}
                    onClick={() => {
                      setDecision('approved')
                      setDecideFor(request)
                    }}
                  >
                    批准
                  </Button>
                  <Button
                    size="small"
                    type="link"
                    danger
                    icon={<CloseOutlined />}
                    onClick={() => {
                      setDecision('changes_requested')
                      setDecideFor(request)
                    }}
                  >
                    要求修改
                  </Button>
                </>
              )}
              {request.status === 'pending' && canSubmit && (
                <Button size="small" type="link" onClick={() => void cancel(request)}>
                  撤销
                </Button>
              )}
            </Space>
          </div>
        )}
      />

      <Modal
        title="提交审核"
        open={submitOpen}
        onCancel={() => setSubmitOpen(false)}
        onOk={() => void submit()}
        okText="提交"
      >
        <Space direction="vertical" style={{ width: '100%' }}>
          <Text>提交时将绑定当前内容版本，审核人可查看提交时快照与后续修改的差异。</Text>
          <TextArea
            rows={3}
            value={note}
            onChange={(e) => setNote(e.target.value)}
            placeholder="提交说明（可选）"
          />
          <MemberSelect
            projectId={projectId}
            value={reviewerId}
            onChange={setReviewerId}
            placeholder="指定审核人（可选，默认通知所有审核人）"
            roleFilter={(m) => m.role === 'reviewer' || m.role === 'owner'}
          />
        </Space>
      </Modal>

      <Modal
        title={decision === 'approved' ? '批准审核' : '要求修改'}
        open={!!decideFor}
        onCancel={() => setDecideFor(null)}
        onOk={() => void decide()}
        okText="确认"
        okButtonProps={{
          disabled: decision === 'changes_requested' && !decideComment.trim(),
        }}
      >
        <Space direction="vertical" style={{ width: '100%' }}>
          <TextArea
            rows={3}
            value={decideComment}
            onChange={(e) => setDecideComment(e.target.value)}
            placeholder={decision === 'approved' ? '批准说明（可选）' : '修改原因（必填）'}
          />
          {decideFor && isOwner && (
            <>
              <Alert
                type="warning"
                message="如果你批准的是自己提交的内容，本次决定属于管理覆盖，必须填写理由"
              />
              <TextArea
                rows={2}
                value={overrideReason}
                onChange={(e) => setOverrideReason(e.target.value)}
                placeholder="覆盖理由（自审时必填）"
              />
            </>
          )}
        </Space>
      </Modal>

      <Modal
        title="提交时快照 vs 当前内容"
        open={!!diffFor}
        onCancel={() => setDiffFor(null)}
        footer={null}
        width={720}
      >
        <Descriptions column={1} size="small" bordered>
          <Descriptions.Item label="提交时快照">
            <pre style={{ maxHeight: 260, overflow: 'auto', fontSize: 12 }}>
              {JSON.stringify(diffData.snapshot, null, 2)}
            </pre>
          </Descriptions.Item>
          <Descriptions.Item label="当前内容">
            <pre style={{ maxHeight: 260, overflow: 'auto', fontSize: 12 }}>
              {JSON.stringify(diffData.current, null, 2)}
            </pre>
          </Descriptions.Item>
        </Descriptions>
      </Modal>
    </div>
  )
}
