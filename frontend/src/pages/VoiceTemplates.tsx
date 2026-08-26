import { useEffect, useState } from 'react'
import {
  Card,
  Typography,
  Space,
  Button,
  Table,
  Tag,
  Modal,
  Form,
  Input,
  Select,
  InputNumber,
  Slider,
  Popconfirm,
  App,
  Switch,
  Divider,
} from 'antd'
import {
  PlusOutlined,
  CopyOutlined,
  DeleteOutlined,
  PlayCircleOutlined,
  EditOutlined,
} from '@ant-design/icons'
import { useNavigate, useParams } from 'react-router-dom'
import { voiceProviderApi, voiceTemplateApi } from '../api'
import type { VoiceTemplate } from '../api/types'

const { Title, Text } = Typography

const SPEAKING_STYLES = [
  '正式稳重',
  '沉稳大气',
  '科技专业',
  '清晰客观',
  '亲和自然',
  '激昂有力',
  '新闻播报',
  '工程解说',
]

const AUTH_TYPES = [
  { label: '供应商内置', value: 'provider_builtin' },
  { label: '企业已授权', value: 'enterprise_licensed' },
  { label: '权利人授权', value: 'custom_authorized' },
  { label: '演示音色', value: 'mock' },
  { label: '来源不明', value: 'unknown' },
]

const AUTH_STATUSES = [
  { label: '已批准', value: 'approved' },
  { label: '待审核', value: 'pending' },
  { label: '已拒绝', value: 'rejected' },
  { label: '已过期', value: 'expired' },
  { label: '仅演示', value: 'mock_only' },
]

export default function VoiceTemplates() {
  const { projectId = '' } = useParams()
  const navigate = useNavigate()
  const { message } = App.useApp()
  const [templates, setTemplates] = useState<VoiceTemplate[]>([])
  const [voices, setVoices] = useState<any[]>([])
  const [caps, setCaps] = useState<Record<string, boolean>>({})
  const [modalOpen, setModalOpen] = useState(false)
  const [editing, setEditing] = useState<VoiceTemplate | null>(null)
  const [previewUrl, setPreviewUrl] = useState<string | null>(null)
  const [form] = Form.useForm()
  const [provider, setProvider] = useState('mock')

  const fetchAll = () => {
    voiceTemplateApi.list().then((res) => setTemplates(res.data)).catch(() => {})
    voiceProviderApi.list().then((res) => {
      if (res.data[0]) {
        setProvider(res.data[0].provider)
        setCaps(res.data[0].capabilities || {})
        voiceProviderApi.voices(res.data[0].provider).then((r) => setVoices(r.data)).catch(() => {})
      }
    }).catch(() => {})
  }

  useEffect(fetchAll, [])

  const openCreate = () => {
    setEditing(null)
    form.resetFields()
    setModalOpen(true)
  }

  const openEdit = (t: VoiceTemplate) => {
    setEditing(t)
    form.setFieldsValue({
      name: t.name,
      description: t.description,
      provider_voice_id: t.provider_voice_id || t.voice_name,
      model_name: t.model_name,
      speaking_style: t.speaking_style,
      speed: t.speed,
      pitch: t.pitch,
      volume: t.volume,
      pause_strength: t.pause_strength,
      emotion: t.emotion,
      authorization_type: t.authorization_type,
      authorization_status: t.authorization_status,
      authorization_note: t.authorization_note,
      is_enabled: t.is_enabled,
      preview_text: t.preview_text,
    })
    setModalOpen(true)
  }

  const handleSave = async () => {
    const values = await form.validateFields().catch(() => null)
    if (!values) return
    try {
      if (editing) {
        await voiceTemplateApi.update(editing.id, values)
        message.success('模板已更新')
      } else {
        await voiceTemplateApi.create({ ...values, voice_provider: provider, project_id: projectId })
        message.success('模板已创建')
      }
      setModalOpen(false)
      fetchAll()
    } catch {
      // 已提示
    }
  }

  const handlePreview = async (t: VoiceTemplate) => {
    try {
      const res = await voiceTemplateApi.preview(t.id)
      setPreviewUrl(res.data.url)
    } catch {
      // 已提示
    }
  }

  const handleDuplicate = async (t: VoiceTemplate) => {
    try {
      await voiceTemplateApi.duplicate(t.id)
      message.success('已复制模板')
      fetchAll()
    } catch {
      // 已提示
    }
  }

  const handleDelete = async (t: VoiceTemplate) => {
    try {
      await voiceTemplateApi.remove(t.id)
      message.success('模板已删除')
      fetchAll()
    } catch {
      // 已提示
    }
  }

  const authStatusColor = (s: string) => {
    if (s === 'approved') return 'success'
    if (s === 'mock_only') return 'default'
    if (s === 'pending') return 'warning'
    return 'error'
  }

  return (
    <div>
      <div className="page-header">
        <div className="page-heading">
          <Title level={4} style={{ marginBottom: 4 }}>
            配音模板管理
          </Title>
          <Text type="secondary" className="page-description">系统 / 企业 / 项目级配音模板，含音色风格与授权管理</Text>
        </div>
        <Button className="page-actions" onClick={() => navigate(`/project/${projectId}/voice`)}>返回配音工作区</Button>
      </div>

      <Card>
        <Space style={{ marginBottom: 12 }}>
          <Button type="primary" icon={<PlusOutlined />} onClick={openCreate}>
            新建模板
          </Button>
        </Space>
        <Table
          rowKey="id"
          dataSource={templates}
          pagination={false}
          columns={[
            { title: '模板名称', dataIndex: 'name', width: 160 },
            { title: '风格', dataIndex: 'speaking_style', width: 90, render: (v) => v || '-' },
            { title: '音色', dataIndex: 'provider_voice_id', width: 100, render: (v, r) => v || r.voice_name },
            {
              title: '语速',
              dataIndex: 'speed',
              width: 70,
              render: (v) => `${v ?? '-'}x`,
            },
            {
              title: '授权',
              dataIndex: 'authorization_status',
              width: 90,
              render: (v) => <Tag color={authStatusColor(v)}>{v}</Tag>,
            },
            { title: '类型', dataIndex: 'is_system', width: 70, render: (v) => (v ? '系统' : '自定义') },
            {
              title: '状态',
              dataIndex: 'is_enabled',
              width: 70,
              render: (v) => (v ? <Tag color="success">启用</Tag> : <Tag>停用</Tag>),
            },
            {
              title: '操作',
              width: 260,
              render: (_, t) => (
                <Space size={4}>
                  <Button size="small" icon={<PlayCircleOutlined />} onClick={() => handlePreview(t)}>
                    试听
                  </Button>
                  <Button size="small" icon={<EditOutlined />} onClick={() => openEdit(t)}>
                    编辑
                  </Button>
                  <Button size="small" icon={<CopyOutlined />} onClick={() => handleDuplicate(t)}>
                    复制
                  </Button>
                  {!t.is_system && (
                    <Popconfirm title="删除该模板？" onConfirm={() => handleDelete(t)}>
                      <Button size="small" danger icon={<DeleteOutlined />} />
                    </Popconfirm>
                  )}
                </Space>
              ),
            },
          ]}
        />
      </Card>

      {/* 试听 */}
      <Modal title="音色试听" open={!!previewUrl} onCancel={() => setPreviewUrl(null)} footer={null}>
        {previewUrl && <audio controls src={previewUrl} style={{ width: '100%' }} autoPlay />}
        {provider === 'mock' && (
          <Text type="secondary" style={{ display: 'block', marginTop: 8 }}>Mock 试听为演示提示音，非真实朗读。</Text>
        )}
      </Modal>

      {/* 新建/编辑 */}
      <Modal
        title={editing ? '编辑配音模板' : '新建配音模板'}
        open={modalOpen}
        onCancel={() => setModalOpen(false)}
        onOk={handleSave}
        width={640}
        okText="保存"
      >
        <Form form={form} layout="vertical" initialValues={{ speed: 1.0, pitch: 1.0, volume: 1.0, pause_strength: 1.0, authorization_type: 'provider_builtin', authorization_status: 'approved', is_enabled: true }}>
          <Form.Item label="模板名称" name="name" rules={[{ required: true, message: '请输入模板名称' }]}>
            <Input placeholder="如：工程解说·沉稳大气" />
          </Form.Item>
          <Form.Item label="描述" name="description">
            <Input.TextArea rows={2} placeholder="模板用途说明" />
          </Form.Item>
          <Space size={16} style={{ width: '100%' }} wrap>
            <Form.Item label="音色" name="provider_voice_id" style={{ width: 180 }}>
              <Select
                placeholder="选择音色"
                options={voices.map((v) => ({ value: v.id, label: `${v.name}（${v.gender}）` }))}
              />
            </Form.Item>
            <Form.Item label="说话风格" name="speaking_style" style={{ width: 160 }}>
              <Select options={SPEAKING_STYLES.map((s) => ({ label: s, value: s }))} allowClear />
            </Form.Item>
            <Form.Item label="模型" name="model_name" style={{ width: 140 }}>
              <Input placeholder="tts-1" />
            </Form.Item>
          </Space>
          <Form.Item label={`语速：${form.getFieldValue('speed') ?? 1.0}`}>
            <Form.Item name="speed" noStyle>
              <Slider min={0.85} max={1.2} step={0.01} disabled={!caps.speed_control} />
            </Form.Item>
          </Form.Item>
          <Space size={24} wrap>
            <Form.Item label={`音调：${form.getFieldValue('pitch') ?? 1.0}`}>
              <Form.Item name="pitch" noStyle>
                <Slider min={0.5} max={1.5} step={0.05} style={{ width: 120 }} disabled={!caps.pitch_control} />
              </Form.Item>
            </Form.Item>
            <Form.Item label={`音量：${form.getFieldValue('volume') ?? 1.0}`}>
              <Form.Item name="volume" noStyle>
                <Slider min={0} max={2} step={0.05} style={{ width: 120 }} disabled={!caps.volume_control} />
              </Form.Item>
            </Form.Item>
            <Form.Item label={`停顿：${form.getFieldValue('pause_strength') ?? 1.0}`}>
              <Form.Item name="pause_strength" noStyle>
                <Slider min={0.3} max={2} step={0.1} style={{ width: 120 }} />
              </Form.Item>
            </Form.Item>
          </Space>
          <Space size={16} wrap>
            <Form.Item label="授权类型" name="authorization_type" style={{ width: 160 }}>
              <Select options={AUTH_TYPES} />
            </Form.Item>
            <Form.Item label="授权状态" name="authorization_status" style={{ width: 150 }}>
              <Select options={AUTH_STATUSES} />
            </Form.Item>
            <Form.Item label="启用" name="is_enabled" valuePropName="checked">
              <Switch />
            </Form.Item>
          </Space>
          <Form.Item label="授权备注" name="authorization_note">
            <Input placeholder="授权来源、合同编号等" />
          </Form.Item>
          <Form.Item label="试听文本" name="preview_text">
            <Input placeholder="留空使用默认试听文本" />
          </Form.Item>
        </Form>
        <Divider />
        <Text type="warning">
          授权状态为 pending / rejected / expired / unknown 的音色不得用于正式视频导出；mock_only 仅限演示。
        </Text>
      </Modal>
    </div>
  )
}
