import { useEffect, useState } from 'react'
import {
  App,
  Alert,
  Avatar,
  Button,
  Card,
  Col,
  Collapse,
  Form,
  Input,
  Modal,
  Popconfirm,
  Row,
  Space,
  Statistic,
  Switch,
  Select,
  Table,
  Tag,
  Typography,
} from 'antd'
import {
  CheckCircleOutlined,
  LockOutlined,
  LogoutOutlined,
  PlusOutlined,
  SafetyOutlined,
  SettingOutlined,
  TeamOutlined,
  UserOutlined,
} from '@ant-design/icons'
import dayjs from 'dayjs'
import { useNavigate } from 'react-router-dom'
import { adminApi, authApi } from '../api'
import type { AIConfiguration, AIProviderSetting, User } from '../api/types'
import { useAuth } from '../stores/auth'

const { Title, Text } = Typography

type MemberFormValues = {
  email: string
  username: string
  full_name?: string
  company?: string
  password: string
  is_superuser?: boolean
}

export default function AccountSettings() {
  const navigate = useNavigate()
  const { message } = App.useApp()
  const { user, logout } = useAuth()
  const [profile, setProfile] = useState<User | null>(user)
  const [profileForm] = Form.useForm()
  const [profileSaving, setProfileSaving] = useState(false)
  const [members, setMembers] = useState<User[]>([])
  const [membersLoading, setMembersLoading] = useState(false)
  const [memberModalOpen, setMemberModalOpen] = useState(false)
  const [memberSaving, setMemberSaving] = useState(false)
  const [memberForm] = Form.useForm<MemberFormValues>()
  const [aiConfig, setAiConfig] = useState<AIConfiguration | null>(null)
  const [aiSaving, setAiSaving] = useState(false)

  useEffect(() => {
    setProfile(user)
    profileForm.setFieldsValue({
      email: user?.email,
      username: user?.username,
      full_name: user?.full_name,
      company: user?.company,
      password: undefined,
    })
  }, [profileForm, user])

  const loadMembers = () => {
    if (!user?.is_superuser) return
    setMembersLoading(true)
    adminApi
      .users()
      .then((res) => setMembers(res.data))
      .finally(() => setMembersLoading(false))
  }

  useEffect(() => {
    loadMembers()
    // 权限变化时重新拉取一次人员列表。
  }, [user?.is_superuser])

  useEffect(() => {
    if (!user?.is_superuser) return
    authApi.aiConfiguration()
      .then((res) => setAiConfig(res.data))
      .catch(() => {})
  }, [user?.is_superuser])

  const updateAiProvider = (provider: string, patch: Partial<AIProviderSetting>) => {
    setAiConfig((current) => current ? {
      ...current,
      providers: current.providers.map((item) => item.provider === provider ? { ...item, ...patch } : item),
    } : current)
  }

  const updateAiStage = (stage: string, patch: { provider?: string; model?: string }) => {
    setAiConfig((current) => current ? {
      ...current,
      stages: { ...current.stages, [stage]: { ...current.stages[stage], ...patch } },
    } : current)
  }

  const saveAiSettings = async (providerName?: string) => {
    if (!aiConfig) return
    setAiSaving(true)
    try {
      const providers = Object.fromEntries(aiConfig.providers.map((item) => [item.provider, {
        base_url: item.base_url,
        model: item.model,
        ...(item.api_key ? { api_key: item.api_key } : {}),
      }]))
      const res = await authApi.saveAiConfiguration({ providers, stages: aiConfig.stages })
      setAiConfig(res.data)
      message.success(providerName ? `${providerName} 配置已保存，后续任务会按环节使用新设置` : 'AI 配置已保存，后续任务会按环节使用新设置')
    } catch {
      // 拦截器已提示
    } finally {
      setAiSaving(false)
    }
  }

  const handleProfileSave = async () => {
    const values = await profileForm.validateFields()
    const payload = {
      username: values.username,
      full_name: values.full_name || undefined,
      company: values.company || undefined,
      ...(values.password ? { password: values.password } : {}),
    }
    setProfileSaving(true)
    try {
      const res = await authApi.updateMe(payload)
      setProfile(res.data)
      profileForm.setFieldValue('password', undefined)
      message.success('账号资料已保存')
    } catch {
      // 拦截器已提示
    } finally {
      setProfileSaving(false)
    }
  }

  const handleCreateMember = async () => {
    const values = await memberForm.validateFields()
    setMemberSaving(true)
    try {
      await adminApi.createUser(values)
      message.success('人员已添加')
      setMemberModalOpen(false)
      memberForm.resetFields()
      loadMembers()
    } catch {
      // 拦截器已提示
    } finally {
      setMemberSaving(false)
    }
  }

  const updateMember = async (member: User, payload: Parameters<typeof adminApi.updateUser>[1], successMessage: string) => {
    try {
      await adminApi.updateUser(member.id, payload)
      message.success(successMessage)
      loadMembers()
    } catch {
      // 拦截器已提示
    }
  }

  const activeMemberCount = members.filter((member) => member.is_active).length
  const adminMemberCount = members.filter((member) => member.is_superuser).length

  return (
    <div className="account-settings-page">
      <div className="page-header account-settings-header">
        <div>
          <Title level={4} style={{ marginBottom: 4 }}>
            账号设置
          </Title>
          <Text type="secondary">管理登录资料、权限和平台人员</Text>
        </div>
        <Button icon={<LogoutOutlined />} onClick={() => { logout(); navigate('/login') }}>
          退出登录
        </Button>
      </div>

      <div className="account-settings-grid">
        <div className="account-settings-main">
          <Card
            title={<Space><UserOutlined />我的账号</Space>}
            extra={profile?.is_superuser ? <Tag color="blue" icon={<SafetyOutlined />}>超级管理员</Tag> : <Tag>普通成员</Tag>}
          >
            <div className="account-profile-summary">
              <Avatar size={56} icon={<UserOutlined />} />
              <div>
                <Text strong style={{ fontSize: 16 }}>{profile?.full_name || profile?.username || '未命名成员'}</Text>
                <Text type="secondary" style={{ display: 'block', marginTop: 3 }}>{profile?.email}</Text>
              </div>
            </div>
            <Form form={profileForm} layout="vertical" onFinish={handleProfileSave} className="account-profile-form">
              <Row gutter={16}>
                <Col xs={24} md={12}>
                  <Form.Item label="登录邮箱" name="email">
                    <Input disabled />
                  </Form.Item>
                </Col>
                <Col xs={24} md={12}>
                  <Form.Item label="用户名" name="username" rules={[{ required: true, min: 2, message: '请输入至少 2 个字符' }]}>
                    <Input />
                  </Form.Item>
                </Col>
                <Col xs={24} md={12}>
                  <Form.Item label="姓名" name="full_name">
                    <Input placeholder="用于平台内展示" />
                  </Form.Item>
                </Col>
                <Col xs={24} md={12}>
                  <Form.Item label="所属单位" name="company">
                    <Input placeholder="例如：中建某局" />
                  </Form.Item>
                </Col>
                <Col xs={24}>
                  <Form.Item
                    label="修改密码"
                    name="password"
                    extra="留空表示不修改；密码长度至少 6 位"
                    rules={[{ min: 6, message: '密码长度至少 6 位' }]}
                  >
                    <Input.Password prefix={<LockOutlined />} placeholder="输入新密码" />
                  </Form.Item>
                </Col>
              </Row>
              <Button type="primary" htmlType="submit" loading={profileSaving} icon={<CheckCircleOutlined />}>
                保存账号资料
              </Button>
            </Form>
          </Card>
          {profile?.is_superuser && aiConfig && (
            <Card
              style={{ marginTop: 16 }}
              title={<Space><SettingOutlined />AI 服务与环节</Space>}
              extra={<Button type="primary" loading={aiSaving} onClick={() => saveAiSettings()}>保存 AI 配置</Button>}
            >
              <Text type="secondary" style={{ display: 'block', marginBottom: 14 }}>
                所有 Provider、模型、接口地址和业务环节绑定集中在这里管理。密钥只显示末四位，留空不会覆盖原密钥。
              </Text>
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(230px, 1fr))', gap: 10, marginBottom: 18 }}>
                {Object.entries(aiConfig.stage_options).map(([stage, label]) => {
                  const binding = aiConfig.stages[stage] || {}
                  const available = aiConfig.providers.filter((provider) => {
                    if (stage === 'image') return ['seedream', 'minimax', 'openai', 'mock'].includes(provider.provider)
                    if (stage === 'video') return ['seedance', 'mock'].includes(provider.provider)
                    if (stage === 'voice') return ['volcengine', 'minimax', 'openai', 'mock'].includes(provider.provider)
                    // 解说词、工程信息提取和提示词大师统一使用 Kimi；Mock 仅保留给演示/测试。
                    return ['kimi', 'mock'].includes(provider.provider)
                  })
                  return (
                    <div key={stage} style={{ padding: '10px 12px', border: '1px solid #e5e7eb', borderRadius: 8, background: '#fafbfc' }}>
                      <Text strong style={{ display: 'block', marginBottom: 7 }}>{label}</Text>
                      <Select
                        value={binding.provider}
                        style={{ width: '100%', marginBottom: 6 }}
                        options={available.map((provider) => ({ label: provider.label, value: provider.provider }))}
                        onChange={(provider) => updateAiStage(stage, { provider })}
                      />
                      <Input
                        value={binding.model || ''}
                        placeholder={stage === 'prompt_master' && binding.provider === 'kimi' ? '例如 kimi-k3；留空使用 Kimi 默认模型' : '使用 Provider 默认模型'}
                        onChange={(event) => updateAiStage(stage, { model: event.target.value })}
                      />
                      {stage === 'prompt_master' && binding.provider === 'kimi' && (
                        <>
                          <Text type="secondary" style={{ display: 'block', marginTop: 4, fontSize: 11 }}>
                            提示词大师会把首尾帧传给 Kimi。Kimi Code Key（sk-kimi-）使用 https://api.kimi.com/coding/v1；
                            Moonshot 开放平台 Key 使用 https://api.moonshot.cn/v1 或 https://api.moonshot.ai/v1。
                          </Text>
                        </>
                      )}
                    </div>
                  )
                })}
              </div>
              <Collapse
                ghost
                items={aiConfig.providers.map((provider) => ({
                  key: provider.provider,
                  label: <Space><Text strong>{provider.label}</Text><Tag color={provider.api_key_set ? 'green' : 'default'}>{provider.api_key_set ? provider.api_key_hint : '未配置密钥'}</Tag></Space>,
                  children: (
                    <>
                    <Row gutter={12}>
                      <Col xs={24} md={8}><Text type="secondary">接口地址</Text><Input style={{ marginTop: 5 }} value={provider.base_url} onChange={(event) => updateAiProvider(provider.provider, { base_url: event.target.value })} /></Col>
                      <Col xs={24} md={8}><Text type="secondary">默认模型</Text><Input style={{ marginTop: 5 }} value={provider.model} onChange={(event) => updateAiProvider(provider.provider, { model: event.target.value })} /></Col>
                      <Col xs={24} md={8}><Text type="secondary">API Key</Text><Input.Password style={{ marginTop: 5 }} placeholder={provider.api_key_hint} value={provider.api_key || ''} onChange={(event) => updateAiProvider(provider.provider, { api_key: event.target.value })} /></Col>
                    </Row>
                    <Space style={{ marginTop: 12 }}>
                      <Button type="primary" size="small" icon={<CheckCircleOutlined />} loading={aiSaving} onClick={() => saveAiSettings(provider.label)}>
                        确认保存此 Provider
                      </Button>
                      <Text type="secondary" style={{ fontSize: 12 }}>输入 API Key 后点击此按钮立即生效</Text>
                    </Space>
                    {provider.provider === 'kimi' && (
                      <Alert
                        type="info"
                        showIcon
                        style={{ marginTop: 12 }}
                        message="提示词大师支持 Kimi Code K3 多模态"
                        description="Kimi Code Key（sk-kimi-）请使用 https://api.kimi.com/coding/v1，模型填 k3 或 kimi-k3；系统会自动规范化。Moonshot 平台 Key 则使用对应的 moonshot.cn/ai 接口。"
                      />
                    )}
                    </>
                  ),
                }))}
              />
            </Card>
          )}
        </div>

        <div className="account-settings-side">
          <Card title={<Space><SettingOutlined />账号概览</Space>}>
            <Row gutter={[12, 18]}>
              <Col span={12}><Statistic title="账号状态" value={profile?.is_active ? '正常' : '已停用'} valueStyle={{ fontSize: 20, color: profile?.is_active ? '#16805c' : '#c53030' }} /></Col>
              <Col span={12}><Statistic title="加入时间" value={profile?.created_at ? dayjs(profile.created_at).format('YYYY-MM-DD') : '-'} valueStyle={{ fontSize: 18 }} /></Col>
            </Row>
          </Card>
          <Text type="secondary" className="account-permission-note">
            {profile?.is_superuser ? '你可以管理平台人员、账号状态和管理员权限。' : '当前账号可使用项目工作区；人员管理仅对超级管理员开放。'}
          </Text>
        </div>
      </div>

      {profile?.is_superuser ? (
        <Card
          className="account-members-card"
          title={<Space><TeamOutlined />Admin 人员系统</Space>}
          extra={<Button type="primary" icon={<PlusOutlined />} onClick={() => { memberForm.resetFields(); setMemberModalOpen(true) }}>添加人员</Button>}
        >
          <div className="account-member-stats">
            <Tag color="green">正常成员 {activeMemberCount}</Tag>
            <Tag color="blue">管理员 {adminMemberCount}</Tag>
            <Text type="secondary">停用账号不会删除历史项目和任务记录</Text>
          </div>
          <Table<User>
            rowKey="id"
            loading={membersLoading}
            dataSource={members}
            pagination={false}
            scroll={{ x: 760 }}
            columns={[
              {
                title: '人员',
                render: (_, member) => (
                  <Space>
                    <Avatar size="small" icon={<UserOutlined />} />
                    <span>
                      <Text strong>{member.full_name || member.username}</Text>
                      <Text type="secondary" style={{ display: 'block', fontSize: 12 }}>{member.email}</Text>
                    </span>
                  </Space>
                ),
              },
              { title: '所属单位', dataIndex: 'company', render: (value) => value || <Text type="secondary">未填写</Text> },
              { title: '角色', dataIndex: 'is_superuser', render: (value) => value ? <Tag color="blue">管理员</Tag> : <Tag>成员</Tag> },
              { title: '状态', dataIndex: 'is_active', render: (value) => value ? <Tag color="green">正常</Tag> : <Tag color="red">已停用</Tag> },
              { title: '加入时间', dataIndex: 'created_at', width: 120, render: (value) => dayjs(value).format('YYYY-MM-DD') },
              {
                title: '操作',
                width: 210,
                render: (_, member) => {
                  const isSelf = member.id === user?.id
                  return (
                    <Space wrap>
                      <Popconfirm
                        title={member.is_active ? '确认停用该账号？' : '确认启用该账号？'}
                        onConfirm={() => updateMember(member, { is_active: !member.is_active }, member.is_active ? '账号已停用' : '账号已启用')}
                        disabled={isSelf}
                      >
                        <Button size="small" disabled={isSelf}>
                          {member.is_active ? '停用' : '启用'}
                        </Button>
                      </Popconfirm>
                      <Popconfirm
                        title={member.is_superuser ? '取消该人员的管理员权限？' : '授予该人员管理员权限？'}
                        onConfirm={() => updateMember(member, { is_superuser: !member.is_superuser }, member.is_superuser ? '已取消管理员权限' : '已授予管理员权限')}
                        disabled={isSelf}
                      >
                        <Button size="small" disabled={isSelf}>
                          {member.is_superuser ? '取消管理员' : '设为管理员'}
                        </Button>
                      </Popconfirm>
                    </Space>
                  )
                },
              },
            ]}
          />
        </Card>
      ) : (
        <Card className="account-members-card">
          <Text type="secondary">当前账号没有人员管理权限。如需添加或停用成员，请联系超级管理员。</Text>
        </Card>
      )}

      <Modal
        title="添加平台人员"
        open={memberModalOpen}
        onCancel={() => setMemberModalOpen(false)}
        onOk={handleCreateMember}
        okText="创建账号"
        confirmLoading={memberSaving}
        destroyOnClose
      >
        <Form form={memberForm} layout="vertical" initialValues={{ is_superuser: false }}>
          <Form.Item label="登录邮箱" name="email" rules={[{ required: true, type: 'email', message: '请输入有效邮箱' }]}>
            <Input placeholder="name@company.com" />
          </Form.Item>
          <Row gutter={12}>
            <Col span={12}>
              <Form.Item label="用户名" name="username" rules={[{ required: true, min: 2, message: '请输入至少 2 个字符' }]}>
                <Input />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item label="初始密码" name="password" rules={[{ required: true, min: 6, message: '至少 6 位' }]}>
                <Input.Password />
              </Form.Item>
            </Col>
          </Row>
          <Form.Item label="姓名" name="full_name">
            <Input />
          </Form.Item>
          <Form.Item label="所属单位" name="company">
            <Input />
          </Form.Item>
          <Form.Item label="管理员权限" name="is_superuser" valuePropName="checked" extra="管理员可查看并管理人员系统">
            <Switch checkedChildren="管理员" unCheckedChildren="成员" />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  )
}
