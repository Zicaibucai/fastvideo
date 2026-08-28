import { useCallback, useEffect, useState } from 'react'
import {
  Badge,
  Button,
  Card,
  Col,
  DatePicker,
  Descriptions,
  Empty,
  Form,
  Input,
  List,
  Modal,
  Row,
  Select,
  Space,
  Statistic,
  Table,
  Tabs,
  Tag,
  Typography,
  message,
} from 'antd'
import {
  AuditOutlined,
  CheckCircleOutlined,
  ClockCircleOutlined,
  CommentOutlined,
  PlusOutlined,
  TeamOutlined,
} from '@ant-design/icons'
import { useParams, useSearchParams } from 'react-router-dom'
import dayjs from 'dayjs'
import { collabApi } from '../api'
import type {
  AuditLogEntry,
  CollabSummary,
  ProjectComment,
  ProjectReviewStatus,
  ProjectWorkItem,
  ReviewRequest,
} from '../api/types'
import { useProjectPermissions, ROLE_LABELS } from '../hooks/useProjectPermissions'
import ReviewStateTag from '../components/collab/ReviewStateTag'
import ReviewPanel from '../components/collab/ReviewPanel'
import CommentPanel from '../components/collab/CommentPanel'
import MemberSelect from '../components/collab/MemberSelect'
import MembersTab from '../components/collab/MembersTab'

const { Text, Title } = Typography

const TASK_STATUS: Record<string, { color: string; label: string }> = {
  todo: { color: 'default', label: '待处理' },
  in_progress: { color: 'processing', label: '进行中' },
  blocked: { color: 'error', label: '受阻' },
  done: { color: 'success', label: '已完成' },
  cancelled: { color: 'default', label: '已取消' },
}

const PRIORITY: Record<string, { color: string; label: string }> = {
  low: { color: 'default', label: '低' },
  medium: { color: 'blue', label: '中' },
  high: { color: 'orange', label: '高' },
  urgent: { color: 'red', label: '紧急' },
}

/** 协作与审核中心 */
export default function Collaboration() {
  const { projectId = '' } = useParams()
  const [searchParams, setSearchParams] = useSearchParams()
  const tab = searchParams.get('tab') || 'overview'
  const { has, role, reviewPolicy } = useProjectPermissions()

  const [summary, setSummary] = useState<CollabSummary | null>(null)
  const [reviewStatus, setReviewStatus] = useState<ProjectReviewStatus | null>(null)

  const loadSummary = useCallback(async () => {
    if (!projectId) return
    try {
      const [s, r] = await Promise.all([
        collabApi.summary(projectId),
        collabApi.reviewStatus(projectId),
      ])
      setSummary(s.data)
      setReviewStatus(r.data)
    } catch {
      /* 权限不足时保持空态 */
    }
  }, [projectId])

  useEffect(() => {
    void loadSummary()
  }, [loadSummary])

  const items = [
    {
      key: 'overview',
      label: '协作总览',
      children: (
        <OverviewTab summary={summary} reviewStatus={reviewStatus} reviewPolicy={reviewPolicy} />
      ),
    },
    {
      key: 'tasks',
      label: (
        <Badge count={summary?.my_open_task_count} size="small" offset={[8, 0]}>
          待办
        </Badge>
      ),
      children: <TasksTab projectId={projectId} />,
    },
    {
      key: 'reviews',
      label: (
        <Badge count={summary?.pending_review_count} size="small" offset={[8, 0]}>
          审核
        </Badge>
      ),
      children: <ReviewsTab projectId={projectId} onChanged={loadSummary} />,
    },
    {
      key: 'comments',
      label: '修改意见',
      children: <CommentsTab projectId={projectId} />,
    },
    {
      key: 'members',
      label: (
        <span>
          <TeamOutlined /> 项目成员
        </span>
      ),
      children: <MembersTab projectId={projectId} />,
    },
  ]
  if (has('audit.view')) {
    items.push({
      key: 'audit',
      label: (
        <span>
          <AuditOutlined /> 审计记录
        </span>
      ),
      children: <AuditTab projectId={projectId} />,
    })
  }

  return (
    <div style={{ padding: 24 }}>
      <Space direction="vertical" size={4} style={{ marginBottom: 16 }}>
        <Title level={4} style={{ margin: 0 }}>协作与审核</Title>
        <Text type="secondary">
          我的角色：{ROLE_LABELS[role ?? ''] ?? role ?? '加载中'} · 审核策略：
          {reviewPolicy === 'required' ? '正式导出前必须完成审核' : reviewPolicy === 'recommended' ? '建议审核（不阻断导出）' : '未启用审核'}
        </Text>
      </Space>
      <Tabs activeKey={tab} onChange={(key) => setSearchParams({ tab: key })} items={items} />
    </div>
  )
}

function OverviewTab({
  summary,
  reviewStatus,
  reviewPolicy,
}: {
  summary: CollabSummary | null
  reviewStatus: ProjectReviewStatus | null
  reviewPolicy: string
}) {
  const targetBrief = (label: string, brief?: { state: string; submitted_by?: string; submitted_at?: string }) => (
    <Card size="small" style={{ flex: 1 }}>
      <Space direction="vertical" size={4}>
        <Text type="secondary">{label}</Text>
        <ReviewStateTag state={brief?.state} />
        {brief?.submitted_at && (
          <Text type="secondary" style={{ fontSize: 12 }}>
            最近提交：{new Date(brief.submitted_at).toLocaleString('zh-CN')}
          </Text>
        )}
      </Space>
    </Card>
  )
  return (
    <Space direction="vertical" size={16} style={{ width: '100%' }}>
      <Row gutter={16}>
        <Col span={4}><Card size="small"><Statistic title="我的待办" value={summary?.my_open_task_count ?? 0} prefix={<ClockCircleOutlined />} /></Card></Col>
        <Col span={4}><Card size="small"><Statistic title="项目待办" value={summary?.open_task_count ?? 0} /></Card></Col>
        <Col span={4}><Card size="small"><Statistic title="待审核" value={summary?.pending_review_count ?? 0} prefix={<CheckCircleOutlined />} /></Card></Col>
        <Col span={4}><Card size="small"><Statistic title="未解决评论" value={summary?.open_comment_count ?? 0} prefix={<CommentOutlined />} /></Card></Col>
        <Col span={4}><Card size="small"><Statistic title="项目成员" value={summary?.member_count ?? 0} prefix={<TeamOutlined />} /></Card></Col>
      </Row>
      <Card size="small" title={`审核状态（策略：${reviewPolicy === 'required' ? '必需' : reviewPolicy === 'recommended' ? '建议' : '未启用'}）`}>
        <Space style={{ width: '100%' }} size={16} wrap>
          {targetBrief('关键工程信息', reviewStatus?.facts)}
          {targetBrief('分镜文稿', reviewStatus?.storyboard)}
          {targetBrief('视频工程', reviewStatus?.video_project ?? undefined)}
        </Space>
      </Card>
      <Card size="small" title="最近协作动态">
        <List
          size="small"
          dataSource={summary?.recent_activity ?? []}
          locale={{ emptyText: <Empty description="暂无动态" /> }}
          renderItem={(log) => (
            <List.Item>
              <Space>
                <Tag>{log.action}</Tag>
                <Text>{log.user_name || '系统'}</Text>
                <Text type="secondary" style={{ fontSize: 12 }}>
                  {log.created_at ? new Date(log.created_at).toLocaleString('zh-CN') : ''}
                </Text>
              </Space>
            </List.Item>
          )}
        />
      </Card>
    </Space>
  )
}

function TasksTab({ projectId }: { projectId: string }) {
  const { has } = useProjectPermissions()
  const [items, setItems] = useState<ProjectWorkItem[]>([])
  const [loading, setLoading] = useState(false)
  const [filters, setFilters] = useState<{ status?: string; priority?: string; mine?: boolean }>({})
  const [createOpen, setCreateOpen] = useState(false)
  const [form] = Form.useForm()
  const canCreate = has('task.create')
  const canAssign = has('task.assign')

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const resp = await collabApi.workItems(projectId, filters)
      setItems(resp.data)
    } finally {
      setLoading(false)
    }
  }, [projectId, filters])

  useEffect(() => {
    void load()
  }, [load])

  const create = async () => {
    const values = await form.validateFields()
    await collabApi.createWorkItem(projectId, {
      title: values.title,
      description: values.description,
      assignee_id: values.assignee_id,
      priority: values.priority,
      due_at: values.due_at ? dayjs(values.due_at).toISOString() : undefined,
    })
    message.success('待办已创建')
    setCreateOpen(false)
    form.resetFields()
    await load()
  }

  const setStatus = async (item: ProjectWorkItem, status: string) => {
    try {
      await collabApi.updateWorkItem(projectId, item.id, { status })
      await load()
    } catch {
      /* 拦截器已提示 */
    }
  }

  return (
    <Space direction="vertical" size={12} style={{ width: '100%' }}>
      <Space wrap>
        <Select
          allowClear
          placeholder="状态"
          style={{ width: 120 }}
          onChange={(v) => setFilters((f) => ({ ...f, status: v }))}
          options={Object.entries(TASK_STATUS).map(([value, s]) => ({ value, label: s.label }))}
        />
        <Select
          allowClear
          placeholder="优先级"
          style={{ width: 120 }}
          onChange={(v) => setFilters((f) => ({ ...f, priority: v }))}
          options={Object.entries(PRIORITY).map(([value, p]) => ({ value, label: p.label }))}
        />
        <Button type={filters.mine ? 'primary' : 'default'} onClick={() => setFilters((f) => ({ ...f, mine: !f.mine }))}>
          只看我的
        </Button>
        {canCreate && (
          <Button type="primary" icon={<PlusOutlined />} onClick={() => setCreateOpen(true)}>
            创建待办
          </Button>
        )}
      </Space>
      <Table
        rowKey="id"
        size="small"
        loading={loading}
        dataSource={items}
        pagination={{ pageSize: 15 }}
        columns={[
          { title: '标题', dataIndex: 'title', key: 'title' },
          {
            title: '负责人',
            key: 'assignee',
            render: (_: unknown, i: ProjectWorkItem) => i.assignee_name || <Text type="secondary">未分派</Text>,
          },
          {
            title: '优先级',
            key: 'priority',
            render: (_: unknown, i: ProjectWorkItem) => {
              const p = PRIORITY[i.priority] ?? PRIORITY.medium
              return <Tag color={p.color}>{p.label}</Tag>
            },
          },
          {
            title: '状态',
            key: 'status',
            render: (_: unknown, i: ProjectWorkItem) => (
              <Select
                size="small"
                value={i.status}
                style={{ width: 110 }}
                onChange={(v) => void setStatus(i, v)}
                options={Object.entries(TASK_STATUS).map(([value, s]) => ({ value, label: s.label }))}
              />
            ),
          },
          {
            title: '关联对象',
            key: 'target',
            render: (_: unknown, i: ProjectWorkItem) => i.target_label || '-',
          },
          {
            title: '到期时间',
            key: 'due_at',
            render: (_: unknown, i: ProjectWorkItem) => {
              if (!i.due_at) return '-'
              const overdue = i.status !== 'done' && dayjs(i.due_at).isBefore(dayjs())
              return (
                <Text type={overdue ? 'danger' : undefined}>
                  {dayjs(i.due_at).format('MM-DD HH:mm')}
                  {overdue && '（已逾期）'}
                </Text>
              )
            },
          },
          {
            title: '创建人',
            key: 'created_by',
            render: (_: unknown, i: ProjectWorkItem) => i.created_by_name || '-',
          },
        ]}
      />
      <Modal
        title="创建待办"
        open={createOpen}
        onCancel={() => setCreateOpen(false)}
        onOk={() => void create()}
        okText="创建"
      >
        <Form form={form} layout="vertical" initialValues={{ priority: 'medium' }}>
          <Form.Item name="title" label="标题" rules={[{ required: true, message: '请填写标题' }]}>
            <Input maxLength={255} />
          </Form.Item>
          <Form.Item name="description" label="描述">
            <Input.TextArea rows={2} />
          </Form.Item>
          <Form.Item name="assignee_id" label={canAssign ? '负责人（可分派给任意成员）' : '负责人'}>
            <MemberSelect projectId={projectId} style={{ width: '100%' }} />
          </Form.Item>
          <Form.Item name="priority" label="优先级">
            <Select
              options={Object.entries(PRIORITY).map(([value, p]) => ({ value, label: p.label }))}
            />
          </Form.Item>
          <Form.Item name="due_at" label="到期时间">
            <DatePicker showTime style={{ width: '100%' }} />
          </Form.Item>
        </Form>
      </Modal>
    </Space>
  )
}

function ReviewsTab({ projectId, onChanged }: { projectId: string; onChanged: () => void }) {
  const [reviews, setReviews] = useState<ReviewRequest[]>([])
  const [loading, setLoading] = useState(false)
  const [filter, setFilter] = useState<string>()
  const [mineOnly, setMineOnly] = useState(false)

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const resp = await collabApi.reviews(projectId, {
        ...(filter ? { status: filter } : {}),
        ...(mineOnly ? { mine: true } : {}),
      })
      setReviews(resp.data)
    } finally {
      setLoading(false)
    }
  }, [projectId, filter, mineOnly])

  useEffect(() => {
    void load()
  }, [load])

  const TARGET_LABEL: Record<string, string> = {
    facts: '工程信息',
    fact: '工程参数',
    storyboard: '分镜文稿',
    shot: '分镜',
    video_project: '视频工程',
  }

  return (
    <Space direction="vertical" size={12} style={{ width: '100%' }}>
      <Space>
        <Select
          allowClear
          placeholder="状态筛选"
          style={{ width: 160 }}
          onChange={setFilter}
          options={[
            { value: 'pending', label: '待审核' },
            { value: 'changes_requested', label: '要求修改' },
            { value: 'approved', label: '已批准' },
            { value: 'superseded', label: '已失效' },
            { value: 'cancelled', label: '已撤销' },
          ]}
        />
        <Button type={mineOnly ? 'primary' : 'default'} onClick={() => setMineOnly((v) => !v)}>
          我提交的
        </Button>
        <Text type="secondary" style={{ fontSize: 12 }}>
          在「工程信息核对」「解说词与分镜」「视频工程」页面可对对应内容提交审核；此处集中处理所有审核请求。
        </Text>
      </Space>
      <List
        loading={loading}
        dataSource={reviews}
        locale={{ emptyText: <Empty description="暂无审核请求" /> }}
        renderItem={(r) => (
          <Card size="small" style={{ marginBottom: 8 }} key={r.id}>
            <Descriptions size="small" column={4}>
              <Descriptions.Item label="对象">{r.target_label || TARGET_LABEL[r.target_type] || r.target_type}</Descriptions.Item>
              <Descriptions.Item label="状态"><ReviewStateTag state={r.current_state || r.status} /></Descriptions.Item>
              <Descriptions.Item label="提交人">{r.submitted_by_name}</Descriptions.Item>
              <Descriptions.Item label="提交时间">{new Date(r.submitted_at).toLocaleString('zh-CN')}</Descriptions.Item>
            </Descriptions>
            {r.decisions.map((d) => (
              <div key={d.id} style={{ marginTop: 4, fontSize: 12 }}>
                <Tag color={d.decision === 'approved' ? 'green' : 'orange'}>
                  {d.decision === 'approved' ? '批准' : '要求修改'}
                </Tag>
                {d.reviewer_name}：{d.comment || '（无说明）'}
                {d.is_override && <Tag color="purple">管理覆盖：{d.override_reason}</Tag>}
              </div>
            ))}
          </Card>
        )}
      />
      <Card size="small" title="快捷提交审核">
        <Tabs
          size="small"
          items={[
            {
              key: 'facts',
              label: '工程信息（批量）',
              children: <ReviewPanel projectId={projectId} targetType="facts" onChanged={() => { void load(); onChanged() }} />,
            },
            {
              key: 'storyboard',
              label: '分镜文稿（整份）',
              children: <ReviewPanel projectId={projectId} targetType="storyboard" onChanged={() => { void load(); onChanged() }} />,
            },
          ]}
        />
      </Card>
    </Space>
  )
}

function CommentsTab({ projectId }: { projectId: string }) {
  const [comments, setComments] = useState<ProjectComment[]>([])
  const [loading, setLoading] = useState(false)
  const [status, setStatus] = useState<string>()

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const resp = await collabApi.comments(projectId, status ? { status } : {})
      setComments(resp.data)
    } finally {
      setLoading(false)
    }
  }, [projectId, status])

  useEffect(() => {
    void load()
  }, [load])

  return (
    <Space direction="vertical" size={12} style={{ width: '100%' }}>
      <Select
        allowClear
        placeholder="状态"
        style={{ width: 140 }}
        onChange={setStatus}
        options={[
          { value: 'open', label: '未解决' },
          { value: 'resolved', label: '已解决' },
        ]}
      />
      <Table
        rowKey="id"
        size="small"
        loading={loading}
        dataSource={comments}
        pagination={{ pageSize: 15 }}
        columns={[
          {
            title: '对象',
            key: 'target',
            render: (_: unknown, c: ProjectComment) => (
              <Space size={4}>
                <Tag>{c.target_type}</Tag>
                <span>{c.target_label}</span>
                {c.is_blocking && <Tag color="red">阻断</Tag>}
              </Space>
            ),
          },
          { title: '内容', dataIndex: 'body', key: 'body', ellipsis: true },
          { title: '作者', dataIndex: 'author_name', key: 'author_name', width: 120 },
          {
            title: '状态',
            key: 'status',
            width: 100,
            render: (_: unknown, c: ProjectComment) =>
              c.status === 'resolved' ? <Tag color="green">已解决</Tag> : <Tag>未解决</Tag>,
          },
          {
            title: '时间',
            key: 'created_at',
            width: 170,
            render: (_: unknown, c: ProjectComment) => new Date(c.created_at).toLocaleString('zh-CN'),
          },
        ]}
      />
    </Space>
  )
}

function AuditTab({ projectId }: { projectId: string }) {
  const [logs, setLogs] = useState<AuditLogEntry[]>([])
  const [loading, setLoading] = useState(false)

  useEffect(() => {
    setLoading(true)
    collabApi
      .auditLogs(projectId, { limit: 200 })
      .then((resp) => setLogs(resp.data))
      .finally(() => setLoading(false))
  }, [projectId])

  return (
    <Table
      rowKey="id"
      size="small"
      loading={loading}
      dataSource={logs}
      pagination={{ pageSize: 20 }}
      columns={[
        {
          title: '时间',
          key: 'created_at',
          width: 170,
          render: (_: unknown, l: AuditLogEntry) => new Date(l.created_at).toLocaleString('zh-CN'),
        },
        { title: '操作者', dataIndex: 'user_name', key: 'user_name', width: 120 },
        {
          title: '动作',
          dataIndex: 'action',
          key: 'action',
          width: 200,
          render: (a: string) => <Tag>{a}</Tag>,
        },
        { title: '对象类型', dataIndex: 'entity_type', key: 'entity_type', width: 120 },
        {
          title: '摘要',
          key: 'detail',
          render: (_: unknown, l: AuditLogEntry) => (
            <Text style={{ fontSize: 12 }}>{l.note || JSON.stringify(l.detail ?? {})}</Text>
          ),
        },
      ]}
    />
  )
}
