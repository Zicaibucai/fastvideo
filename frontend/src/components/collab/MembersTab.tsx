import { useCallback, useEffect, useState } from 'react'
import {
  Alert,
  Button,
  Card,
  Form,
  Input,
  Modal,
  Popconfirm,
  Select,
  Space,
  Table,
  Tabs,
  Tag,
  Typography,
  message,
} from 'antd'
import {
  CopyOutlined,
  CrownOutlined,
  MailOutlined,
  SwapOutlined,
} from '@ant-design/icons'
import { collabApi } from '../../api'
import type {
  InvitationCreated,
  ProjectInvitation,
  ProjectMember,
  ProjectRole,
  RolePermission,
} from '../../api/types'
import { ROLE_LABELS, useProjectPermissions } from '../../hooks/useProjectPermissions'

const { Text, Paragraph } = Typography

const ROLE_OPTIONS: { value: ProjectRole; label: string }[] = [
  { value: 'bid_manager', label: '投标负责人' },
  { value: 'technical_editor', label: '技术编辑' },
  { value: 'media_editor', label: '视频编辑' },
  { value: 'reviewer', label: '审核人' },
  { value: 'viewer', label: '只读成员' },
]

const INVITE_STATUS: Record<string, { color: string; label: string }> = {
  pending: { color: 'processing', label: '待接受' },
  accepted: { color: 'success', label: '已接受' },
  revoked: { color: 'default', label: '已撤销' },
  expired: { color: 'warning', label: '已过期' },
}

/** 项目成员管理：列表、邀请、角色修改、移除、所有权转移、权限说明 */
export default function MembersTab({ projectId }: { projectId: string }) {
  const { has, project, refresh } = useProjectPermissions()
  const [members, setMembers] = useState<ProjectMember[]>([])
  const [invitations, setInvitations] = useState<ProjectInvitation[]>([])
  const [rolePerms, setRolePerms] = useState<RolePermission[]>([])
  const [loading, setLoading] = useState(false)
  const [inviteOpen, setInviteOpen] = useState(false)
  const [inviteResult, setInviteResult] = useState<InvitationCreated | null>(null)
  const [transferOpen, setTransferOpen] = useState(false)
  const [transferTarget, setTransferTarget] = useState<string>()
  const [transferReason, setTransferReason] = useState('')
  const [form] = Form.useForm()

  const canManage = has('member.manage')
  const canTransfer = has('ownership.transfer')
  const activeOwners = members.filter((m) => m.role === 'owner' && m.status === 'active')

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const resp = await collabApi.members(projectId)
      setMembers(resp.data)
      if (canManage) {
        const inv = await collabApi.invitations(projectId)
        setInvitations(inv.data)
      }
    } finally {
      setLoading(false)
    }
  }, [projectId, canManage])

  useEffect(() => {
    void load()
    collabApi.roles().then((r) => setRolePerms(r.data)).catch(() => {})
  }, [load])

  const invite = async () => {
    const values = await form.validateFields()
    const resp = await collabApi.invite(projectId, values.email, values.role)
    setInviteResult(resp.data)
    form.resetFields()
    await load()
  }

  const copyLink = async (url: string) => {
    const full = `${window.location.origin}${url}`
    try {
      await navigator.clipboard.writeText(full)
      message.success('邀请链接已复制')
    } catch {
      Modal.info({ title: '邀请链接', content: full })
    }
  }

  const changeRole = async (member: ProjectMember, role: ProjectRole) => {
    try {
      await collabApi.updateMemberRole(projectId, member.id, role)
      message.success('角色已更新')
      await load()
    } catch {
      /* 拦截器已提示（如最后一个 owner 保护） */
    }
  }

  const remove = async (member: ProjectMember) => {
    try {
      await collabApi.removeMember(projectId, member.id)
      message.success('成员已移除')
      await load()
    } catch {
      /* 拦截器已提示 */
    }
  }

  const transfer = async () => {
    if (!transferTarget) return
    await collabApi.transferOwnership(projectId, transferTarget, transferReason || undefined)
    message.success('所有权已转移')
    setTransferOpen(false)
    await load()
    await refresh()
  }

  const memberColumns = [
    {
      title: '成员',
      key: 'user',
      render: (_: unknown, m: ProjectMember) => (
        <Space>
          {m.role === 'owner' && <CrownOutlined style={{ color: '#faad14' }} />}
          <span>{m.full_name || m.username}</span>
          <Text type="secondary" style={{ fontSize: 12 }}>{m.email}</Text>
        </Space>
      ),
    },
    {
      title: '角色',
      key: 'role',
      render: (_: unknown, m: ProjectMember) =>
        canManage && m.role !== 'owner' && m.status === 'active' ? (
          <Select
            size="small"
            value={m.role}
            style={{ width: 140 }}
            options={ROLE_OPTIONS}
            onChange={(role) => void changeRole(m, role)}
          />
        ) : (
          <Tag color={m.role === 'owner' ? 'gold' : 'default'}>{ROLE_LABELS[m.role] ?? m.role}</Tag>
        ),
    },
    {
      title: '状态',
      key: 'status',
      render: (_: unknown, m: ProjectMember) => {
        const map = {
          active: { color: 'green', label: '正常' },
          suspended: { color: 'orange', label: '已停用' },
          left: { color: 'default', label: '已退出' },
        } as const
        const s = map[m.status] ?? map.left
        return <Tag color={s.color}>{s.label}</Tag>
      },
    },
    {
      title: '加入时间',
      key: 'joined_at',
      render: (_: unknown, m: ProjectMember) => new Date(m.joined_at).toLocaleString('zh-CN'),
    },
    ...(canManage
      ? [
          {
            title: '操作',
            key: 'actions',
            render: (_: unknown, m: ProjectMember) => {
              if (m.status !== 'active') return null
              const isLastOwner = m.role === 'owner' && activeOwners.length <= 1
              if (m.role === 'owner') {
                return isLastOwner ? (
                  <Text type="secondary" style={{ fontSize: 12 }}>
                    唯一所有者，转移所有权后方可退出
                  </Text>
                ) : null
              }
              return (
                <Popconfirm title="移除该成员？" onConfirm={() => void remove(m)}>
                  <Button size="small" danger type="link">
                    移除
                  </Button>
                </Popconfirm>
              )
            },
          },
        ]
      : []),
  ]

  const invitationColumns = [
    { title: '邮箱', dataIndex: 'email', key: 'email' },
    {
      title: '角色',
      dataIndex: 'role',
      key: 'role',
      render: (role: string) => ROLE_LABELS[role] ?? role,
    },
    {
      title: '状态',
      dataIndex: 'status',
      key: 'status',
      render: (status: string) => {
        const s = INVITE_STATUS[status] ?? { color: 'default', label: status }
        return <Tag color={s.color}>{s.label}</Tag>
      },
    },
    {
      title: '过期时间',
      dataIndex: 'expires_at',
      key: 'expires_at',
      render: (v: string) => new Date(v).toLocaleString('zh-CN'),
    },
    {
      title: '操作',
      key: 'actions',
      render: (_: unknown, inv: ProjectInvitation) =>
        inv.status === 'pending' ? (
          <Space>
            <Button size="small" type="link" onClick={() => void collabApi.resendInvitation(projectId, inv.id).then((r) => setInviteResult(r.data))}>
              重发
            </Button>
            <Popconfirm
              title="撤销该邀请？"
              onConfirm={() => void collabApi.revokeInvitation(projectId, inv.id).then(load)}
            >
              <Button size="small" danger type="link">
                撤销
              </Button>
            </Popconfirm>
          </Space>
        ) : null,
    },
  ]

  return (
    <Space direction="vertical" size={16} style={{ width: '100%' }}>
      {canManage && (
        <Space wrap>
          <Button type="primary" icon={<MailOutlined />} onClick={() => setInviteOpen(true)}>
            邀请成员
          </Button>
          {canTransfer && (
            <Button icon={<SwapOutlined />} onClick={() => setTransferOpen(true)}>
              转移项目所有权
            </Button>
          )}
        </Space>
      )}
      {!canManage && (
        <Alert type="info" message="只有项目所有者可以管理成员、发送邀请和转移所有权" showIcon />
      )}

      <Card title={`成员列表（${members.filter((m) => m.status === 'active').length} 人）`} size="small">
        <Table
          rowKey="id"
          size="small"
          loading={loading}
          columns={memberColumns}
          dataSource={members}
          pagination={false}
        />
      </Card>

      {canManage && invitations.length > 0 && (
        <Card title="邀请记录" size="small">
          <Table
            rowKey="id"
            size="small"
            columns={invitationColumns}
            dataSource={invitations}
            pagination={{ pageSize: 8 }}
          />
        </Card>
      )}

      <Card title="角色权限说明" size="small">
        <Tabs
          size="small"
          items={rolePerms.map((rp) => ({
            key: rp.role,
            label: rp.label,
            children: (
              <Paragraph style={{ fontSize: 12 }}>
                {rp.permissions.sort().map((p) => (
                  <Tag key={p} style={{ marginBottom: 4 }}>{p}</Tag>
                ))}
              </Paragraph>
            ),
          }))}
        />
      </Card>

      <Modal
        title="邀请成员"
        open={inviteOpen}
        onCancel={() => setInviteOpen(false)}
        onOk={() => void invite()}
        okText="发送邀请"
      >
        <Alert
          type="info"
          style={{ marginBottom: 12 }}
          message="系统未配置邮件服务时，可创建后复制邀请链接发给对方。邀请 7 天内有效，仅可使用一次。"
        />
        <Form form={form} layout="vertical" initialValues={{ role: 'viewer' }}>
          <Form.Item
            name="email"
            label="邮箱"
            rules={[{ required: true, type: 'email', message: '请输入有效邮箱' }]}
          >
            <Input placeholder="member@example.com" />
          </Form.Item>
          <Form.Item name="role" label="项目角色" rules={[{ required: true }]}>
            <Select options={ROLE_OPTIONS} />
          </Form.Item>
        </Form>
      </Modal>

      <Modal
        title="邀请已创建"
        open={!!inviteResult}
        onCancel={() => setInviteResult(null)}
        footer={
          <Button type="primary" icon={<CopyOutlined />} onClick={() => inviteResult && void copyLink(inviteResult.invite_url)}>
            复制邀请链接
          </Button>
        }
      >
        <Paragraph>邀请链接仅显示这一次，请立即复制并发送给被邀请人：</Paragraph>
        <Paragraph code copyable={{ text: inviteResult ? `${window.location.origin}${inviteResult.invite_url}` : '' }}>
          {inviteResult ? `${window.location.origin}${inviteResult.invite_url}` : ''}
        </Paragraph>
        <Text type="secondary">有效期 7 天，仅可由 {inviteResult?.email} 的账号接受一次。</Text>
      </Modal>

      <Modal
        title="转移项目所有权"
        open={transferOpen}
        onCancel={() => setTransferOpen(false)}
        onOk={() => void transfer()}
        okText="确认转移"
        okButtonProps={{ disabled: !transferTarget, danger: true }}
      >
        <Alert
          type="warning"
          style={{ marginBottom: 12 }}
          message="转移后你将成为投标负责人，对方成为项目所有者（获得成员管理、删除项目等全部权限）"
        />
        <Space direction="vertical" style={{ width: '100%' }}>
          <Select
            style={{ width: '100%' }}
            placeholder="选择新的所有者（必须是当前项目成员）"
            value={transferTarget}
            onChange={setTransferTarget}
            options={members
              .filter((m) => m.status === 'active' && m.role !== 'owner')
              .map((m) => ({
                value: m.user_id,
                label: `${m.full_name || m.username}（${ROLE_LABELS[m.role]}）`,
              }))}
          />
          <Input.TextArea
            rows={2}
            placeholder="转移原因（可选，将记录到审计日志）"
            value={transferReason}
            onChange={(e) => setTransferReason(e.target.value)}
          />
        </Space>
      </Modal>
    </Space>
  )
}
