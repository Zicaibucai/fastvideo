import { useEffect, useState } from 'react'
import {
  Card,
  Typography,
  Button,
  Space,
  Table,
  Tag,
  Modal,
  Form,
  Input,
  InputNumber,
  App,
  Tooltip,
  Popconfirm,
  Empty,
  Select,
  Alert,
  Descriptions,
  Switch,
  Statistic,
  Row,
  Col,
  Progress,
} from 'antd'
import {
  PlayCircleOutlined,
  ReloadOutlined,
  DeleteOutlined,
  HistoryOutlined,
  PictureOutlined,
  SoundOutlined,
  VideoCameraOutlined,
  UpOutlined,
  DownOutlined,
  SettingOutlined,
  WarningOutlined,
  LinkOutlined,
  CopyOutlined,
} from '@ant-design/icons'
import { useParams, useNavigate } from 'react-router-dom'
import { storyboardApi, assetApi, voiceApi, scoringApi } from '../api'
import type { StoryboardShot, VoiceTemplate, StoryboardSummary, SourceReference } from '../api/types'
import { TaskTag, useTaskPolling } from '../components/TaskStatus'

const { Title, Text, Paragraph } = Typography

const SECTION_OPTIONS = ['片头', '项目概况', '施工部署', '项目重难点', '施工方案', '保证措施', '片尾']
const VISUAL_TYPES = [
  { label: '标题', value: 'title' },
  { label: '模型图片', value: 'model_image' },
  { label: '现场照片', value: 'site_photo' },
  { label: 'AI生成图片', value: 'generated_image' },
  { label: 'AI生成视频', value: 'generated_video' },
  { label: 'BIM动画', value: 'bim_animation' },
  { label: '信息图表', value: 'infographic' },
]

const FACT_STATUS_MAP: Record<string, { label: string; color: string }> = {
  verified: { label: '已核实', color: 'success' },
  partial: { label: '部分核实', color: 'warning' },
  unverified: { label: '未验证', color: 'error' },
  conflict: { label: '冲突', color: 'volcano' },
}

export default function Storyboard() {
  const { projectId = '' } = useParams()
  const navigate = useNavigate()
  const { message } = App.useApp()
  const [shots, setShots] = useState<StoryboardShot[]>([])
  const [summary, setSummary] = useState<StoryboardSummary | null>(null)
  const [loading, setLoading] = useState(false)
  const [generating, setGenerating] = useState(false)
  const [genTaskId, setGenTaskId] = useState<string | null>(null)
  const [voices, setVoices] = useState<VoiceTemplate[]>([])
  const [editShot, setEditShot] = useState<StoryboardShot | null>(null)
  const [editForm] = Form.useForm()
  const [genForm] = Form.useForm()
  const [genModalOpen, setGenModalOpen] = useState(false)
  const [historyShot, setHistoryShot] = useState<StoryboardShot | null>(null)
  const [scoringNames, setScoringNames] = useState<Record<string, string>>({})

  const fetchShots = () => {
    setLoading(true)
    Promise.all([
      storyboardApi.list(projectId),
      storyboardApi.summary(projectId),
      scoringApi.list(projectId),
    ])
      .then(([shotsRes, summaryRes, scoringRes]) => {
        setShots(shotsRes.data)
        setSummary(summaryRes.data)
        const names: Record<string, string> = {}
        scoringRes.data.forEach((s) => (names[s.id] = s.title))
        setScoringNames(names)
      })
      .finally(() => setLoading(false))
  }

  useEffect(fetchShots, [projectId])

  useEffect(() => {
    voiceApi.list(projectId).then((res) => setVoices(res.data)).catch(() => {})
  }, [projectId])

  // 轮询生成任务
  useTaskPolling(genTaskId, () => {
    setGenTaskId(null)
    setGenerating(false)
    fetchShots()
  })

  const handleGenerate = () => {
    genForm.setFieldsValue({
      section_count: 10,
      tone: '专业庄重',
      target_duration_seconds: 300,
      video_purpose: '投标答辩',
      include_company_intro: true,
      include_construction_simulation: true,
      chars_per_minute: 260,
    })
    setGenModalOpen(true)
  }

  const handleGenerateSubmit = async () => {
    const values = await genForm.validateFields()
    setGenerating(true)
    setGenModalOpen(false)
    try {
      const res = await storyboardApi.generate(projectId, values)
      setGenTaskId(res.data.task_id)
      message.info('解说词智能拆解任务已提交，正在处理…')
    } catch {
      setGenerating(false)
    }
  }

  const handleEdit = (shot: StoryboardShot) => {
    setEditShot(shot)
    editForm.setFieldsValue({
      title: shot.title,
      section: shot.section,
      narration: shot.narration,
      visual_type: shot.visual_type,
      visual_description: shot.visual_description,
      duration_seconds: shot.duration_seconds,
      source_page: shot.source_page,
      fact_check_status: shot.fact_check_status,
    })
  }

  const handleSaveEdit = async () => {
    if (!editShot) return
    const values = await editForm.validateFields()
    try {
      await storyboardApi.update(projectId, editShot.id, values)
      message.success('已保存')
      setEditShot(null)
      fetchShots()
    } catch {
      // 拦截器已提示
    }
  }

  const handleRestore = async (shot: StoryboardShot, revision: number) => {
    try {
      await storyboardApi.restore(projectId, shot.id, revision)
      message.success('已恢复历史版本')
      setHistoryShot(null)
      fetchShots()
    } catch {
      // 拦截器已提示
    }
  }

  const handleDelete = async (shotId: string) => {
    try {
      await storyboardApi.remove(projectId, shotId)
      message.success('已删除')
      fetchShots()
    } catch {
      // 拦截器已提示
    }
  }

  const handleMove = async (index: number, dir: -1 | 1) => {
    const target = index + dir
    if (target < 0 || target >= shots.length) return
    const next = [...shots]
    ;[next[index], next[target]] = [next[target], next[index]]
    const reordered = next.map((s, i) => ({ ...s, sequence: i + 1 }))
    setShots(reordered)
    try {
      await storyboardApi.reorder(projectId, reordered.map((s) => s.id))
      fetchShots()
    } catch {
      fetchShots()
    }
  }

  const handleRegenerate = async (shot: StoryboardShot) => {
    try {
      await storyboardApi.regenerate(projectId, shot.id, shot.title)
      message.success('重新生成完成')
      fetchShots()
    } catch {
      // 拦截器已提示
    }
  }

  const handleGenImage = async (shot: StoryboardShot) => {
    try {
      await assetApi.aiImage(projectId, shot.id, shot.image_prompt || shot.visual_prompt)
      message.success('画面生成任务已提交')
      setTimeout(fetchShots, 3000)
    } catch {
      // 拦截器已提示
    }
  }

  const handleGenTts = async (shot: StoryboardShot) => {
    const voice = voices[0]
    try {
      await assetApi.aiTts(projectId, shot.id, voice?.voice_name || 'onyx', voice?.speed || 1)
      message.success('配音生成任务已提交')
      setTimeout(fetchShots, 3000)
    } catch {
      // 拦截器已提示
    }
  }

  const handleGenVideo = async (shot: StoryboardShot) => {
    try {
      await assetApi.aiVideo(projectId, shot.id, shot.video_prompt || shot.visual_prompt, shot.duration_seconds || 5)
      message.success('视频生成任务已提交')
      setTimeout(fetchShots, 3000)
    } catch {
      // 拦截器已提示
    }
  }

  const handleDuplicate = async (shot: StoryboardShot) => {
    try {
      const newShot: Partial<StoryboardShot> = {
        title: shot.title ? `${shot.title}(副本)` : '副本',
        section: shot.section,
        narration: shot.narration,
        duration_seconds: shot.duration_seconds,
        visual_type: shot.visual_type,
        visual_prompt: shot.visual_prompt,
        visual_description: shot.visual_description,
        image_prompt: shot.image_prompt,
        video_prompt: shot.video_prompt,
        source_references: shot.source_references,
        scoring_point_ids: shot.scoring_point_ids,
        fact_check_status: shot.fact_check_status,
        sequence: Math.max(...shots.map((s) => s.sequence), 0) + 1,
      }
      await storyboardApi.create(projectId, newShot)
      message.success('已复制，可在编辑中调整内容')
      fetchShots()
    } catch {
      // 拦截器已提示
    }
  }

  const unverifiedShots = shots.filter((s) => s.fact_check_status === 'unverified' || s.fact_check_status === 'conflict').length

  const columns = [
    {
      title: '序号',
      dataIndex: 'sequence',
      width: 70,
      render: (v: number) => (
        <Space direction="vertical" size={0}>
          <b>{v}</b>
          <Space size={0}>
            <Button size="small" type="text" icon={<UpOutlined />} onClick={() => handleMove(v - 1, -1)} />
            <Button size="small" type="text" icon={<DownOutlined />} onClick={() => handleMove(v - 1, 1)} />
          </Space>
        </Space>
      ),
    },
    {
      title: '标题/解说词',
      dataIndex: 'narration',
      render: (v: string, r: StoryboardShot) => (
        <Space direction="vertical" size={2}>
          <Space wrap>
            {r.title && <b>{r.title}</b>}
            {r.section && <Tag color="blue">{r.section}</Tag>}
            <FactTag status={r.fact_check_status} />
            {r.source_references && r.source_references.length > 0 && (
              <Tag icon={<LinkOutlined />} color="geekblue">
                {r.source_references.length} 处来源
              </Tag>
            )}
          </Space>
          <Text type="secondary" style={{ fontSize: 13 }} ellipsis={{ tooltip: v }}>
            {v}
          </Text>
          <Space size={4} wrap>
            {r.duration_seconds && (
              <Text type="secondary" style={{ fontSize: 12 }}>
                时长 {r.duration_seconds}s
              </Text>
            )}
            {r.visual_type && (
              <Tag style={{ fontSize: 11 }}>
                {VISUAL_TYPES.find((t) => t.value === r.visual_type)?.label || r.visual_type}
              </Tag>
            )}
            {r.scoring_point_ids && r.scoring_point_ids.length > 0 && (
              <Space size={2} wrap>
                {r.scoring_point_ids.slice(0, 3).map((sid) => (
                  <Tag key={sid} color="green" style={{ fontSize: 11 }}>
                    {scoringNames[sid] || '评分点'}
                  </Tag>
                ))}
              </Space>
            )}
          </Space>
        </Space>
      ),
    },
    {
      title: '来源页码',
      width: 90,
      render: (_: unknown, r: StoryboardShot) => {
        const pages = (r.source_references || []).map((ref) => ref.page).filter(Boolean) as number[]
        if (pages.length === 0) return <Text type="secondary">—</Text>
        return (
          <Space size={2} wrap>
            {[...new Set(pages)].slice(0, 3).map((p) => (
              <Tag key={p} color="orange">
                P{p}
              </Tag>
            ))}
          </Space>
        )
      },
    },
    {
      title: '画面',
      dataIndex: 'image_asset_id',
      width: 80,
      render: (v: string) => (v ? <Tag color="green">已生成</Tag> : <Text type="secondary">—</Text>),
    },
    {
      title: '配音',
      dataIndex: 'audio_asset_id',
      width: 80,
      render: (v: string) => (v ? <Tag color="purple">已生成</Tag> : <Text type="secondary">—</Text>),
    },
    {
      title: '操作',
      width: 400,
      render: (_: unknown, r: StoryboardShot) => (
        <Space wrap>
          <Button size="small" onClick={() => handleEdit(r)}>编辑</Button>
          <Button size="small" icon={<HistoryOutlined />} onClick={() => setHistoryShot(r)}>
            版本
          </Button>
          <Button size="small" icon={<CopyOutlined />} onClick={() => handleDuplicate(r)}>
            复制
          </Button>
          <Button size="small" icon={<ReloadOutlined />} onClick={() => handleRegenerate(r)}>
            重生成
          </Button>
          <Button size="small" icon={<PictureOutlined />} onClick={() => handleGenImage(r)}>
            画面
          </Button>
          <Button size="small" icon={<SoundOutlined />} onClick={() => handleGenTts(r)}>
            配音
          </Button>
          <Button size="small" icon={<VideoCameraOutlined />} onClick={() => handleGenVideo(r)}>
            视频
          </Button>
          <Popconfirm title="删除该分镜？" onConfirm={() => handleDelete(r.id)}>
            <Button size="small" danger icon={<DeleteOutlined />} />
          </Popconfirm>
        </Space>
      ),
    },
  ]

  return (
    <div>
      <div className="page-header" style={{ display: 'flex', justifyContent: 'space-between' }}>
        <div>
          <Title level={4} style={{ marginBottom: 4 }}>
            解说词与分镜
          </Title>
          <Text type="secondary">
            AI 根据已确认的工程事实与评分点智能拆解解说词，支持来源跳转与人工编辑
          </Text>
        </div>
        <Button type="primary" icon={<SettingOutlined />} onClick={handleGenerate} loading={generating}>
          智能生成解说词
        </Button>
      </div>

      {summary && (
        <Row gutter={16} style={{ marginBottom: 16 }}>
          <Col span={5}>
            <Card size="small">
              <Statistic title="分镜数" value={summary.shot_count} />
            </Card>
          </Col>
          <Col span={5}>
            <Card size="small">
              <Statistic title="总时长" value={summary.total_duration_seconds} suffix="秒" />
            </Card>
          </Col>
          <Col span={5}>
            <Card size="small">
              <Statistic title="总字数" value={summary.total_narration_characters} suffix="字" />
            </Card>
          </Col>
          <Col span={5}>
            <Card size="small">
              <Statistic
                title="评分点覆盖率"
                value={Math.round(summary.scoring_coverage_rate * 100)}
                suffix="%"
                valueStyle={{ color: summary.scoring_coverage_rate > 0.5 ? '#52c41a' : '#faad14' }}
              />
            </Card>
          </Col>
          <Col span={4}>
            <Card size="small">
              <Statistic title="未验证分镜" value={unverifiedShots} valueStyle={{ color: unverifiedShots > 0 ? '#cf1322' : '#52c41a' }} />
            </Card>
          </Col>
        </Row>
      )}

      {unverifiedShots > 0 && (
        <Alert
          type="warning"
          showIcon
          icon={<WarningOutlined />}
          style={{ marginBottom: 16 }}
          message={`有 ${unverifiedShots} 个分镜包含未验证事实`}
          description="未验证数据不会作为确定事实写入，建议在参数台账中确认来源，或编辑分镜补充引用。"
        />
      )}

      <Card>
        {shots.length === 0 ? (
          <Empty description="暂无分镜，点击「智能生成解说词」由 AI 自动拆解">
            <Button type="primary" icon={<PlayCircleOutlined />} onClick={handleGenerate}>
              生成解说词
            </Button>
          </Empty>
        ) : (
          <Table<StoryboardShot>
            rowKey="id"
            loading={loading}
            dataSource={shots}
            columns={columns}
            pagination={false}
            expandable={{
              expandedRowRender: (r) => (
                <div style={{ padding: '0 8px' }}>
                  <Space direction="vertical" style={{ width: '100%' }} size={4}>
                    {r.visual_description && (
                      <Text>🎬 画面：{r.visual_description}</Text>
                    )}
                    {r.image_prompt && (
                      <Text type="secondary" style={{ fontSize: 12 }}>图片提示词：{r.image_prompt}</Text>
                    )}
                    {r.source_references && r.source_references.length > 0 && (
                      <div>
                        <Text strong style={{ fontSize: 12 }}>来源引用：</Text>
                        {r.source_references.map((ref, i) => (
                          <div key={i} style={{ marginLeft: 8, marginTop: 4 }}>
                            <Tag color="geekblue">{ref.documentName}</Tag>
                            <Text style={{ fontSize: 12 }}>
                              P{ref.page} {ref.quote ? `「${ref.quote}」` : ''}
                            </Text>
                          </div>
                        ))}
                      </div>
                    )}
                  </Space>
                </div>
              ),
            }}
          />
        )}
      </Card>

      {/* 生成配置弹窗 */}
      <Modal
        title="智能拆解解说词"
        open={genModalOpen}
        onOk={handleGenerateSubmit}
        onCancel={() => setGenModalOpen(false)}
        okText="开始生成"
        confirmLoading={generating}
        width={560}
      >
        <Form form={genForm} layout="vertical">
          <Row gutter={12}>
            <Col span={12}>
              <Form.Item name="target_duration_seconds" label="视频目标时长（秒）">
                <InputNumber min={60} max={1800} style={{ width: '100%' }} />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item name="section_count" label="分镜数量">
                <InputNumber min={6} max={30} style={{ width: '100%' }} />
              </Form.Item>
            </Col>
          </Row>
          <Form.Item name="tone" label="解说风格">
            <Select
              options={['专业庄重', '科技感', '简洁明快', '宏大叙事'].map((t) => ({ label: t, value: t }))}
            />
          </Form.Item>
          <Form.Item name="video_purpose" label="视频用途">
            <Select
              options={['投标答辩', '企业宣传', '评审汇报', '项目汇报'].map((t) => ({ label: t, value: t }))}
            />
          </Form.Item>
          <Form.Item name="chars_per_minute" label="每分钟参考字数">
            <InputNumber min={120} max={400} style={{ width: '100%' }} />
          </Form.Item>
          <Row gutter={12}>
            <Col span={12}>
              <Form.Item name="include_company_intro" label="包含企业介绍" valuePropName="checked">
                <Switch />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item name="include_construction_simulation" label="包含施工推演" valuePropName="checked">
                <Switch />
              </Form.Item>
            </Col>
          </Row>
        </Form>
      </Modal>

      {/* 编辑弹窗 */}
      <Modal
        title={`编辑分镜 #${editShot?.sequence || ''}`}
        open={!!editShot}
        onOk={handleSaveEdit}
        onCancel={() => setEditShot(null)}
        width={640}
      >
        <Form form={editForm} layout="vertical">
          <Form.Item name="title" label="分镜标题">
            <Input />
          </Form.Item>
          <Form.Item name="section" label="章节">
            <Select options={SECTION_OPTIONS.map((s) => ({ label: s, value: s }))} allowClear />
          </Form.Item>
          <Form.Item name="narration" label="解说词" rules={[{ required: true, message: '请输入解说词' }]}>
            <Input.TextArea rows={4} />
          </Form.Item>
          <Row gutter={12}>
            <Col span={12}>
              <Form.Item name="visual_type" label="画面类型">
                <Select options={VISUAL_TYPES} allowClear />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item name="duration_seconds" label="预计时长（秒）">
                <InputNumber min={1} max={120} style={{ width: '100%' }} />
              </Form.Item>
            </Col>
          </Row>
          <Form.Item name="visual_description" label="画面描述">
            <Input.TextArea rows={2} />
          </Form.Item>
          <Form.Item name="source_page" label="来源页码（招标文件）">
            <InputNumber min={1} style={{ width: '100%' }} placeholder="可选" />
          </Form.Item>
          <Form.Item name="fact_check_status" label="事实校验状态">
            <Select
              options={Object.entries(FACT_STATUS_MAP).map(([k, v]) => ({ label: v.label, value: k }))}
              allowClear
            />
          </Form.Item>
        </Form>
      </Modal>

      {/* 历史版本弹窗 */}
      <Modal
        title={`历史版本 - ${historyShot?.title || '分镜'}`}
        open={!!historyShot}
        onCancel={() => setHistoryShot(null)}
        footer={null}
        width={680}
      >
        {(historyShot?.versions || []).length === 0 && <Empty description="暂无历史版本" />}
        {historyShot?.versions?.map((v) => (
          <Card key={v.revision} size="small" style={{ marginBottom: 8 }}>
            <Space direction="vertical" style={{ width: '100%' }}>
              <Space>
                <Tag color={v.source === 'ai' ? 'blue' : 'green'}>
                  版本 {v.revision} · {v.source === 'ai' ? 'AI生成' : '人工编辑'}
                </Tag>
                <Text type="secondary" style={{ fontSize: 12 }}>{v.created_at}</Text>
              </Space>
              <Paragraph style={{ marginBottom: 0 }}>{v.narration}</Paragraph>
              {v.visual_prompt && (
                <Text type="secondary" style={{ fontSize: 12 }}>画面提示词：{v.visual_prompt}</Text>
              )}
              <Button
                size="small"
                type="primary"
                ghost
                onClick={() => handleRestore(historyShot, v.revision)}
              >
                恢复此版本
              </Button>
            </Space>
          </Card>
        ))}
      </Modal>
    </div>
  )
}

function FactTag({ status }: { status?: string }) {
  if (!status) return null
  const item = FACT_STATUS_MAP[status] || { label: status, color: 'default' }
  return <Tag color={item.color}>{item.label}</Tag>
}
