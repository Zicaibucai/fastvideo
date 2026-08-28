import { useCallback, useEffect, useState } from 'react'
import {
  Button,
  Checkbox,
  Empty,
  Input,
  List,
  Modal,
  Space,
  Tag,
  Typography,
  message,
} from 'antd'
import {
  CheckOutlined,
  DeleteOutlined,
  ReloadOutlined,
  RollbackOutlined,
} from '@ant-design/icons'
import { collabApi } from '../../api'
import type { CollabTargetType, ProjectComment } from '../../api/types'
import { useProjectPermissions } from '../../hooks/useProjectPermissions'

const { Text, Paragraph } = Typography
const { TextArea } = Input

/**
 * 通用评论侧栏内容：挂接到任意业务对象（工程信息/分镜/画面版本/视频工程等）。
 * 不要在业务页面重复实现评论系统，统一使用本组件。
 */
export default function CommentPanel({
  projectId,
  targetType,
  targetId,
  onCreateWorkItem,
}: {
  projectId: string
  targetType: CollabTargetType
  targetId?: string
  onCreateWorkItem?: (comment: ProjectComment) => void
}) {
  const { has } = useProjectPermissions()
  const [comments, setComments] = useState<ProjectComment[]>([])
  const [loading, setLoading] = useState(false)
  const [body, setBody] = useState('')
  const [isBlocking, setIsBlocking] = useState(false)
  const [replyTo, setReplyTo] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)

  const canComment = has('comment.create')
  const canResolve = has('comment.resolve')
  const canModerate = has('project.edit')

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const resp = await collabApi.comments(projectId, {
        target_type: targetType,
        target_id: targetId,
      })
      setComments(resp.data)
    } catch {
      setComments([])
    } finally {
      setLoading(false)
    }
  }, [projectId, targetType, targetId])

  useEffect(() => {
    void load()
  }, [load])

  const submit = async () => {
    if (!body.trim()) return
    setSubmitting(true)
    try {
      await collabApi.createComment(projectId, {
        target_type: targetType,
        target_id: targetId,
        parent_id: replyTo ?? undefined,
        body: body.trim(),
        is_blocking: isBlocking,
      })
      setBody('')
      setReplyTo(null)
      setIsBlocking(false)
      await load()
    } finally {
      setSubmitting(false)
    }
  }

  const toggleResolve = async (comment: ProjectComment) => {
    if (comment.status === 'open') {
      await collabApi.resolveComment(projectId, comment.id)
    } else {
      await collabApi.reopenComment(projectId, comment.id)
    }
    await load()
  }

  const remove = (comment: ProjectComment) => {
    Modal.confirm({
      title: '删除这条评论？',
      onOk: async () => {
        await collabApi.deleteComment(projectId, comment.id)
        message.success('已删除')
        await load()
      },
    })
  }

  const roots = comments.filter((c) => !c.parent_id)
  const repliesOf = (id: string) => comments.filter((c) => c.parent_id === id)

  const renderItem = (comment: ProjectComment, isReply = false) => (
    <div
      key={comment.id}
      style={{
        padding: '8px 12px',
        marginBottom: 8,
        marginLeft: isReply ? 24 : 0,
        background: comment.status === 'resolved' ? '#fafafa' : '#fff',
        border: '1px solid #f0f0f0',
        borderRadius: 8,
        opacity: comment.status === 'resolved' ? 0.75 : 1,
      }}
    >
      <Space size={4} wrap>
        <Text strong>{comment.author_name || '成员'}</Text>
        <Text type="secondary" style={{ fontSize: 12 }}>
          {new Date(comment.created_at).toLocaleString('zh-CN')}
        </Text>
        {comment.is_blocking && <Tag color="red">阻断</Tag>}
        {comment.status === 'resolved' && <Tag color="green">已解决</Tag>}
      </Space>
      <Paragraph style={{ margin: '4px 0', whiteSpace: 'pre-wrap' }}>{comment.body}</Paragraph>
      <Space size={8}>
        {canComment && !isReply && (
          <Button type="link" size="small" onClick={() => setReplyTo(comment.id)}>
            回复
          </Button>
        )}
        {(canResolve || canModerate) && (
          <Button
            type="link"
            size="small"
            icon={comment.status === 'open' ? <CheckOutlined /> : <RollbackOutlined />}
            onClick={() => void toggleResolve(comment)}
          >
            {comment.status === 'open' ? '解决' : '重新打开'}
          </Button>
        )}
        {onCreateWorkItem && comment.status === 'open' && (
          <Button type="link" size="small" onClick={() => onCreateWorkItem(comment)}>
            转待办
          </Button>
        )}
        {canModerate && (
          <Button
            type="link"
            size="small"
            danger
            icon={<DeleteOutlined />}
            onClick={() => remove(comment)}
          />
        )}
      </Space>
    </div>
  )

  return (
    <div>
      <Space style={{ marginBottom: 8 }}>
        <Text type="secondary">共 {comments.length} 条评论</Text>
        <Button size="small" icon={<ReloadOutlined />} onClick={() => void load()} />
      </Space>
      <List
        loading={loading}
        dataSource={roots}
        locale={{ emptyText: <Empty description="暂无评论" /> }}
        renderItem={(comment) => (
          <div key={comment.id}>
            {renderItem(comment)}
            {repliesOf(comment.id).map((reply) => renderItem(reply, true))}
          </div>
        )}
      />
      {canComment ? (
        <div style={{ marginTop: 12 }}>
          {replyTo && (
            <Tag closable onClose={() => setReplyTo(null)} style={{ marginBottom: 4 }}>
              回复评论 {replyTo.slice(0, 8)}
            </Tag>
          )}
          <TextArea
            rows={3}
            value={body}
            onChange={(e) => setBody(e.target.value)}
            placeholder="写下评论或修改意见，@成员姓名 可提醒对方"
            maxLength={4000}
          />
          <Space style={{ marginTop: 8 }}>
            <Checkbox checked={isBlocking} onChange={(e) => setIsBlocking(e.target.checked)}>
              标记为阻断级（阻止正式导出）
            </Checkbox>
            <Button type="primary" loading={submitting} disabled={!body.trim()} onClick={() => void submit()}>
              发表评论
            </Button>
          </Space>
        </div>
      ) : (
        <Text type="secondary">当前角色为只读，无法发表评论</Text>
      )}
    </div>
  )
}
