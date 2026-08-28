import { useEffect, useState } from 'react'
import { Badge, Button, DatePicker, Drawer, Form, Input, Modal, Select, Tabs, Tag } from 'antd'
import { CommentOutlined } from '@ant-design/icons'
import dayjs from 'dayjs'
import { collabApi } from '../../api'
import type { CollabTargetType, ProjectComment } from '../../api/types'
import { useProjectPermissions } from '../../hooks/useProjectPermissions'
import CommentPanel from './CommentPanel'
import ReviewPanel from './ReviewPanel'
import MemberSelect from './MemberSelect'

const REVIEWABLE: CollabTargetType[] = ['facts', 'fact', 'storyboard', 'shot', 'video_project']

/**
 * 通用协作入口按钮：未解决评论数角标 + 打开协作抽屉（评论/审核/待办）。
 * 业务页面只需放置本组件即可接入完整协作能力。
 */
export function CollabEntry({
  projectId,
  targetType,
  targetId,
  label,
  reviewState,
  onReviewChanged,
}: {
  projectId: string
  targetType: CollabTargetType
  targetId?: string
  label?: string
  reviewState?: string
  onReviewChanged?: () => void
}) {
  const [open, setOpen] = useState(false)
  const [openCount, setOpenCount] = useState(0)

  useEffect(() => {
    collabApi
      .comments(projectId, { target_type: targetType, target_id: targetId, status: 'open' })
      .then((resp) => setOpenCount(resp.data.length))
      .catch(() => setOpenCount(0))
  }, [projectId, targetType, targetId, open])

  return (
    <>
      <Badge count={openCount} size="small" offset={[-4, 4]}>
        <Button icon={<CommentOutlined />} onClick={() => setOpen(true)}>
          {label ?? '协作'}
        </Button>
      </Badge>
      <CollabDrawer
        projectId={projectId}
        targetType={targetType}
        targetId={targetId}
        open={open}
        onClose={() => setOpen(false)}
        reviewState={reviewState}
        onReviewChanged={onReviewChanged}
      />
    </>
  )
}

/** 协作抽屉：评论 + 审核 + 快捷待办 */
export function CollabDrawer({
  projectId,
  targetType,
  targetId,
  open,
  onClose,
  reviewState,
  onReviewChanged,
}: {
  projectId: string
  targetType: CollabTargetType
  targetId?: string
  open: boolean
  onClose: () => void
  reviewState?: string
  onReviewChanged?: () => void
}) {
  const { has } = useProjectPermissions()
  const [workItemFor, setWorkItemFor] = useState<ProjectComment | null>(null)
  const [form] = Form.useForm()

  const createWorkItem = async () => {
    const values = await form.validateFields()
    await collabApi.createWorkItem(projectId, {
      title: values.title,
      description: values.description,
      target_type: targetType,
      target_id: targetId,
      assignee_id: values.assignee_id,
      comment_id: workItemFor?.id,
      priority: values.priority || 'medium',
      due_at: values.due_at ? dayjs(values.due_at).toISOString() : undefined,
    })
    setWorkItemFor(null)
    form.resetFields()
  }

  const items = [
    {
      key: 'comments',
      label: '评论与意见',
      children: (
        <CommentPanel
          projectId={projectId}
          targetType={targetType}
          targetId={targetId}
          onCreateWorkItem={has('task.create') ? (c) => setWorkItemFor(c) : undefined}
        />
      ),
    },
  ]
  if (REVIEWABLE.includes(targetType)) {
    items.push({
      key: 'review',
      label: '审核',
      children: (
        <ReviewPanel
          projectId={projectId}
          targetType={targetType}
          targetId={targetId}
          currentState={reviewState}
          onChanged={onReviewChanged}
        />
      ),
    })
  }

  return (
    <Drawer title="协作与审核" width={560} open={open} onClose={onClose}>
      <Tabs items={items} />
      <Modal
        title="评论转为待办"
        open={!!workItemFor}
        onCancel={() => setWorkItemFor(null)}
        onOk={() => void createWorkItem()}
        okText="创建待办"
      >
        {workItemFor && (
          <Tag color="orange" style={{ marginBottom: 8 }}>
            {workItemFor.body.slice(0, 50)}
          </Tag>
        )}
        <Form form={form} layout="vertical" initialValues={{ priority: 'medium' }}>
          <Form.Item name="title" label="待办标题" rules={[{ required: true, message: '请填写标题' }]}>
            <Input maxLength={255} />
          </Form.Item>
          <Form.Item name="description" label="描述">
            <Input.TextArea rows={2} />
          </Form.Item>
          <Form.Item name="assignee_id" label="负责人">
            <MemberSelect projectId={projectId} style={{ width: '100%' }} />
          </Form.Item>
          <Form.Item name="priority" label="优先级">
            <Select
              options={[
                { value: 'low', label: '低' },
                { value: 'medium', label: '中' },
                { value: 'high', label: '高' },
                { value: 'urgent', label: '紧急' },
              ]}
            />
          </Form.Item>
          <Form.Item name="due_at" label="到期时间">
            <DatePicker showTime style={{ width: '100%' }} />
          </Form.Item>
        </Form>
      </Modal>
    </Drawer>
  )
}
