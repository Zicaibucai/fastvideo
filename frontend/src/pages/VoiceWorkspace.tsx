import { useEffect, useMemo, useRef, useState } from 'react'
import {
  Card,
  Typography,
  Space,
  Button,
  List,
  Tag,
  Empty,
  Form,
  Input,
  Select,
  InputNumber,
  Slider,
  Modal,
  Alert,
  Progress,
  Segmented,
  Popconfirm,
  Drawer,
  Table,
  Divider,
  Badge,
  Radio,
} from 'antd'
import {
  PlayCircleOutlined,
  ReloadOutlined,
  CheckOutlined,
  SoundOutlined,
  DeleteOutlined,
  HistoryOutlined,
  BookOutlined,
  ThunderboltOutlined,
  DownloadOutlined,
  FileTextOutlined,
} from '@ant-design/icons'
import { useNavigate, useParams } from 'react-router-dom'
import {
  storyboardApi,
  voiceApi,
  voiceProviderApi,
  voiceTemplateApi,
  downloadVoiceFile,
} from '../api'
import type {
  StoryboardShot,
  VoiceTemplate,
  AudioVersion,
  VoiceEstimate,
  VoiceJob,
  SubtitleSegment,
} from '../api/types'
import PronunciationModal from '../components/PronunciationModal'

const { Title, Text, Paragraph } = Typography

const DURATION_STATUS_MAP: Record<string, { label: string; color: string }> = {
  estimated: { label: '待生成', color: 'default' },
  generating: { label: '生成中', color: 'processing' },
  matched: { label: '时长匹配', color: 'success' },
  slightly_short: { label: '略短', color: 'warning' },
  slightly_long: { label: '略长', color: 'warning' },
  script_adjustment_required: { label: '需调整解说词', color: 'error' },
  failed: { label: '失败', color: 'error' },
}

const QUALITY_STATUS_MAP: Record<string, { label: string; color: string }> = {
  passed: { label: '通过', color: 'success' },
  warning: { label: '警告', color: 'warning' },
  failed: { label: '失败', color: 'error' },
  pending: { label: '待检查', color: 'default' },
}

export default function VoiceWorkspace() {
  const { projectId = '' } = useParams()
  const navigate = useNavigate()
  const [shots, setShots] = useState<StoryboardShot[]>([])
  const [selectedShot, setSelectedShot] = useState<StoryboardShot | null>(null)
  const [templates, setTemplates] = useState<VoiceTemplate[]>([])
  const [versions, setVersions] = useState<AudioVersion[]>([])
  const [estimate, setEstimate] = useState<VoiceEstimate | null>(null)
  const [subtitleData, setSubtitleData] = useState<SubtitleSegment[]>([])
  const [shotFilter, setShotFilter] = useState('all')
  const [selectedTemplateId, setSelectedTemplateId] = useState<string>('')
  const [form] = Form.useForm()
  const selectedSpeed = Form.useWatch('speed', form) ?? 1.0
  const [polling, setPolling] = useState(false)
  const [batchModalOpen, setBatchModalOpen] = useState(false)
  const [dictModalOpen, setDictModalOpen] = useState(false)
  const [subtitleModalOpen, setSubtitleModalOpen] = useState(false)
  const [batchOptions, setBatchOptions] = useState({
    skip_empty: true,
    regenerate_stale: true,
    duration_strategy: 'natural',
  })
  const audioRef = useRef<HTMLAudioElement>(null)
  const [providerCaps, setProviderCaps] = useState<Record<string, boolean>>({})
  const [provider, setProvider] = useState('mock')
  const [recentJobs, setRecentJobs] = useState<VoiceJob[]>([])

  // 加载基础数据
  const fetchAll = () => {
    Promise.all([
      storyboardApi.list(projectId),
      voiceTemplateApi.list(),
      voiceProviderApi.list(),
    ])
      .then(([s, t, p]) => {
        setShots(s.data)
        setTemplates(t.data)
        if (p.data[0]) {
          setProvider(p.data[0].provider)
          setProviderCaps(p.data[0].capabilities || {})
        }
      })
      .catch(() => {})
  }

  useEffect(fetchAll, [projectId])

  // 轮询当前任务
  useEffect(() => {
    if (!polling) return
    const timer = setInterval(() => {
      setPolling(false)
    }, 5000)
    return () => clearInterval(timer)
  }, [polling])

  // 轮询配音任务进度
  useEffect(() => {
    if (!projectId) return
    const load = () => {
      voiceApi.jobs(projectId).then((res) => setRecentJobs(res.data)).catch(() => {})
    }
    load()
    const timer = setInterval(load, 5000)
    return () => clearInterval(timer)
  }, [projectId])

  const filteredShots = useMemo(() => {
    if (shotFilter === 'missing') return shots.filter((s) => !s.audio_asset_id)
    if (shotFilter === 'generating') return shots.filter((s) => s.status === 'ai_generating')
    if (shotFilter === 'needs_adjust') return shots.filter((s) => true) // 由版本状态决定，简化处理
    return shots
  }, [shots, shotFilter])

  const selectedVersion = useMemo(
    () => versions.find((v) => v.is_selected) || null,
    [versions],
  )

  const handleSelectShot = async (shot: StoryboardShot) => {
    setSelectedShot(shot)
    setVersions([])
    setSubtitleData([])
    setEstimate(null)
    voiceApi.versions(projectId, shot.id).then((res) => setVersions(res.data)).catch(() => {})
    voiceApi.estimate(projectId, shot.id, selectedTemplateId || undefined)
      .then((res) => setEstimate(res.data))
      .catch(() => {})
    voiceApi.subtitles(projectId, shot.id).then((res) => setSubtitleData(res.data.subtitle_data)).catch(() => {})
  }

  const handleGenerate = async () => {
    if (!selectedShot) {
      return
    }
    const values = await form.validateFields().catch(() => null)
    if (!values) return
    const payload: Record<string, any> = {
      shot_id: selectedShot.id,
      voice_template_id: selectedTemplateId || null,
      speed: values.speed ?? 1.0,
      pitch: values.pitch ?? 1.0,
      volume: values.volume ?? 1.0,
      pause_strength: values.pause_strength ?? 1.0,
      emotion: values.emotion || undefined,
      output_formats: ['wav', 'mp3'],
      idempotency_key: `gen-${Date.now()}`,
    }
    try {
      const res = await voiceApi.generate(projectId, payload)
      setPolling(true)
      setTimeout(() => {
        handleSelectShot(selectedShot)
        fetchAll()
      }, 2500)
    } catch {
      // 拦截器已提示
    }
  }

  const handleSelectVersion = async (v: AudioVersion) => {
    if (!selectedShot) return
    try {
      await voiceApi.selectVersion(projectId, selectedShot.id, v.id)
      handleSelectShot(selectedShot)
    } catch {
      // 已提示
    }
  }

  const handleDeleteVersion = async (v: AudioVersion) => {
    if (!selectedShot) return
    try {
      await voiceApi.deleteVersion(projectId, selectedShot.id, v.id)
      handleSelectShot(selectedShot)
    } catch {
      // 已提示
    }
  }

  const handleRestoreVersion = async (v: AudioVersion) => {
    if (!selectedShot) return
    try {
      await voiceApi.restoreVersion(projectId, selectedShot.id, v.id)
      handleSelectShot(selectedShot)
    } catch {
      // 已提示
    }
  }

  const handleBatch = async () => {
    try {
      await voiceApi.batch(projectId, {
        voice_template_id: selectedTemplateId || null,
        ...batchOptions,
      })
      setBatchModalOpen(false)
      setPolling(true)
      setTimeout(fetchAll, 3000)
    } catch {
      // 已提示
    }
  }

  const seekTo = (ms: number) => {
    if (audioRef.current) {
      audioRef.current.currentTime = ms / 1000
      audioRef.current.play()
    }
  }

  return (
    <div>
      <div className="page-header">
        <Title level={4} style={{ marginBottom: 4 }}>
          配音制作
        </Title>
        <Space>
          <Text type="secondary">解说词 → 朗读规范化 → AI 配音 → 版本管理 → 字幕生成</Text>
        </Space>
      </div>

      <Alert
        type="info"
        showIcon
        style={{ marginBottom: 12 }}
        message={
          provider === 'mock'
            ? '当前为 Mock 演示模式：使用提示音模拟句子，非真实朗读。正式导出前请配置真实 TTS Provider 并确认音色授权。'
            : '当前使用真实 TTS Provider。正式导出将校验音色授权状态。'
        }
      />

      {/* 顶部操作栏 */}
      <Space wrap style={{ marginBottom: 12 }}>
        <Button type="primary" icon={<ThunderboltOutlined />} onClick={() => setBatchModalOpen(true)}>
          批量生成配音
        </Button>
        <Button icon={<BookOutlined />} onClick={() => setDictModalOpen(true)}>
          发音词典
        </Button>
        <Button icon={<FileTextOutlined />} onClick={() => navigate(`/project/${projectId}/voice-templates`)}>
          配音模板管理
        </Button>
        <Button icon={<DownloadOutlined />} onClick={() => downloadVoiceFile(projectId, 'wav')}>
          导出全部 WAV
        </Button>
        <Button icon={<DownloadOutlined />} onClick={() => downloadVoiceFile(projectId, 'mp3')}>
          导出全部 MP3
        </Button>
        <Button icon={<FileTextOutlined />} onClick={() => downloadVoiceFile(projectId, 'srt')}>
          导出项目 SRT
        </Button>
        {recentJobs.some((j) => j.task_type === 'tts_batch' && (j.status === 'running' || j.status === 'queued')) && (
          <Badge status="processing" text="批量任务进行中" />
        )}
        {recentJobs
          .filter((j) => j.task_type === 'tts_batch' && (j.status === 'running' || j.status === 'queued'))
          .slice(0, 1)
          .map((j) => (
            <Progress key={j.id} type="circle" size={42} percent={j.progress} format={() => `${j.progress}%`} />
          ))}
      </Space>

      <Card styles={{ body: { padding: 0 } }} style={{ height: 'calc(100vh - 260px)' }}>
        <div style={{ display: 'flex', height: '100%' }}>
          {/* 左侧：分镜列表 */}
          <div style={{ width: 260, borderRight: '1px solid #f0f0f0', padding: 12, overflowY: 'auto' }}>
            <Space direction="vertical" style={{ width: '100%' }}>
              <Segmented
                size="small"
                value={shotFilter}
                onChange={(v) => setShotFilter(String(v))}
                options={[
                  { label: '全部', value: 'all' },
                  { label: '缺配音', value: 'missing' },
                  { label: '生成中', value: 'generating' },
                ]}
              />
              <List
                size="small"
                dataSource={filteredShots}
                renderItem={(s) => (
                  <List.Item
                    onClick={() => handleSelectShot(s)}
                    style={{
                      cursor: 'pointer',
                      background: selectedShot?.id === s.id ? '#e6f4ff' : undefined,
                      padding: '6px 8px',
                      borderRadius: 6,
                    }}
                  >
                    <Space direction="vertical" size={0} style={{ width: '100%' }}>
                      <Space style={{ width: '100%', justifyContent: 'space-between' }}>
                        <b style={{ fontSize: 13 }}>#{s.sequence} {s.title}</b>
                      </Space>
                      <Space size={4} wrap>
                        <Text type="secondary" style={{ fontSize: 11 }}>
                          {(s.narration || '').length}字 · {s.duration_seconds ?? '-'}s
                        </Text>
                        {s.audio_asset_id ? (
                          <Tag color="green" style={{ fontSize: 10, margin: 0 }}>有配音</Tag>
                        ) : (
                          <Tag style={{ fontSize: 10, margin: 0 }}>缺配音</Tag>
                        )}
                      </Space>
                    </Space>
                  </List.Item>
                )}
                locale={{ emptyText: '暂无分镜' }}
              />
            </Space>
          </div>

          {/* 中间：配音编辑 */}
          <div style={{ flex: 1, padding: 16, overflowY: 'auto' }}>
            {selectedShot ? (
              <>
                <Space style={{ width: '100%', justifyContent: 'space-between' }}>
                  <Text strong>解说词 #{selectedShot.sequence}</Text>
                  {selectedVersion?.is_mock && (
                    <Tag color="orange">Mock Audio</Tag>
                  )}
                  {selectedVersion?.is_stale && (
                    <Tag color="error">解说词已修改，需要重新生成配音</Tag>
                  )}
                </Space>
                <Paragraph style={{ marginTop: 8, background: '#fafafa', padding: 8, borderRadius: 6 }}>
                  {selectedShot.narration || '（无解说词）'}
                </Paragraph>

                <Divider style={{ margin: '8px 0' }} />
                <Text type="secondary" style={{ fontSize: 12 }}>规范化朗读文本（可人工修改，不影响原解说词）</Text>
                <Input.TextArea
                  rows={2}
                  value={estimate?.normalized_text || ''}
                  style={{ marginTop: 4 }}
                  placeholder="加载估算以显示朗读文本…"
                  onChange={(e) => setEstimate((prev) => (prev ? { ...prev, normalized_text: e.target.value } : prev))}
                />

                {/* 音频播放器 */}
                <div style={{ marginTop: 12 }}>
                  <audio
                    ref={audioRef}
                    controls
                    src={selectedVersion?.audio_url}
                    style={{ width: '100%' }}
                  />
                </div>

                {/* 波形 */}
                {selectedVersion?.waveform_data?.points ? (
                  <div style={{ marginTop: 8, display: 'flex', alignItems: 'center', gap: 1, height: 40 }}>
                    {(selectedVersion.waveform_data.points as number[]).map((p, i) => (
                      <div
                        key={i}
                        style={{
                          flex: 1,
                          height: Math.max(2, Math.round(p * 40)),
                          background: '#1677ff',
                          borderRadius: 1,
                        }}
                      />
                    ))}
                  </div>
                ) : (
                  <Empty description="生成配音后显示波形" style={{ margin: '8px 0' }} />
                )}

                {/* 目标/实际时长对比 */}
                <Space wrap style={{ marginTop: 8 }}>
                  <Tag>目标 {selectedShot.duration_seconds ?? '-'}s</Tag>
                  <Tag>预计 {estimate?.estimated_duration_seconds ?? '-'}s</Tag>
                  <Tag color="blue">实际 {selectedVersion?.actual_duration_seconds ?? '-'}s</Tag>
                  {selectedVersion && (
                    <Tag color={DURATION_STATUS_MAP[selectedVersion.duration_status]?.color}>
                      {DURATION_STATUS_MAP[selectedVersion.duration_status]?.label || selectedVersion.duration_status}
                    </Tag>
                  )}
                </Space>
                {estimate?.suggestion && (
                  <Alert type="info" showIcon style={{ marginTop: 8 }} message={estimate.suggestion} />
                )}

                <Divider style={{ margin: '12px 0' }} />

                {/* 字幕句段 */}
                <Space style={{ width: '100%', justifyContent: 'space-between' }}>
                  <Text strong>字幕句段</Text>
                  <Button size="small" icon={<FileTextOutlined />} onClick={() => setSubtitleModalOpen(true)}>
                    编辑字幕
                  </Button>
                </Space>
                {subtitleData.length === 0 && <Empty description="生成配音后自动生成字幕" style={{ margin: '8px 0' }} />}
                <List
                  size="small"
                  dataSource={subtitleData}
                  renderItem={(seg) => (
                    <List.Item style={{ cursor: 'pointer' }} onClick={() => seekTo(seg.start_ms)}>
                      <Space>
                        <Text type="secondary" style={{ fontSize: 11 }}>
                          {fmtTime(seg.start_ms)}
                        </Text>
                        <Text>{seg.text}</Text>
                      </Space>
                    </List.Item>
                  )}
                  locale={{ emptyText: '' }}
                />

                <Divider style={{ margin: '12px 0' }} />

                {/* 版本列表 */}
                <Text strong>配音版本</Text>
                {versions.length === 0 && <Empty description="暂无配音版本" style={{ margin: '8px 0' }} />}
                <Table
                  size="small"
                  rowKey="id"
                  style={{ marginTop: 8 }}
                  dataSource={versions}
                  pagination={false}
                  columns={[
                    { title: '版本', dataIndex: 'version_number', width: 56, render: (n) => `V${n}` },
                    {
                      title: '时长',
                      width: 70,
                      render: (_, v) => `${v.actual_duration_seconds ?? '-'}s`,
                    },
                    { title: '语速', width: 56, dataIndex: 'speed' },
                    {
                      title: '质量',
                      width: 70,
                      render: (_, v) => (
                        <Tag color={QUALITY_STATUS_MAP[v.quality_status]?.color} style={{ fontSize: 10 }}>
                          {QUALITY_STATUS_MAP[v.quality_status]?.label || v.quality_status}
                        </Tag>
                      ),
                    },
                    {
                      title: '状态',
                      render: (_, v) => (
                        <Space size={2}>
                          {v.is_selected && <Tag color="green" style={{ fontSize: 10, margin: 0 }}>正式</Tag>}
                          {v.is_stale && <Tag color="error" style={{ fontSize: 10, margin: 0 }}>过期</Tag>}
                          {v.is_mock && <Tag style={{ fontSize: 10, margin: 0 }}>Mock</Tag>}
                        </Space>
                      ),
                    },
                    {
                      title: '操作',
                      width: 190,
                      render: (_, v) => (
                        <Space size={4}>
                          {v.audio_url && (
                            <Button size="small" icon={<PlayCircleOutlined />} onClick={() => {
                              if (audioRef.current && v.audio_url) {
                                audioRef.current.src = v.audio_url
                                audioRef.current.play()
                              }
                            }}>
                              试听
                            </Button>
                          )}
                          {!v.is_selected && (
                            <Button size="small" type="primary" icon={<CheckOutlined />} onClick={() => handleSelectVersion(v)}>
                              设为正式
                            </Button>
                          )}
                          <Button size="small" icon={<HistoryOutlined />} onClick={() => handleRestoreVersion(v)} />
                          <Popconfirm title="删除该版本？" onConfirm={() => handleDeleteVersion(v)}>
                            <Button size="small" danger icon={<DeleteOutlined />} />
                          </Popconfirm>
                        </Space>
                      ),
                    },
                  ]}
                />
              </>
            ) : (
              <Empty description="请选择左侧分镜" style={{ marginTop: 80 }} />
            )}
          </div>

          {/* 右侧：模板参数 */}
          <div style={{ width: 300, borderLeft: '1px solid #f0f0f0', padding: 12, overflowY: 'auto' }}>
            <Text strong>配音模板</Text>
            <Select
              style={{ width: '100%', marginTop: 8 }}
              placeholder="选择配音模板"
              value={selectedTemplateId || undefined}
              onChange={(v) => {
                setSelectedTemplateId(v)
                if (selectedShot) handleSelectShot(selectedShot)
              }}
              options={templates.map((t) => ({
                value: t.id,
                label: `${t.name}${t.voice_provider === 'mock' || t.voice_provider === 'disabled' ? '（演示）' : ''}`,
              }))}
            />

            <Form
              form={form}
              layout="vertical"
              style={{ marginTop: 8 }}
              initialValues={{ speed: 1.0, pitch: 1.0, volume: 1.0, pause_strength: 1.0 }}
            >
              <Form.Item label={`语速：${selectedSpeed}`}>
                <Form.Item name="speed" noStyle>
                  <Slider min={0.85} max={1.2} step={0.01} disabled={!providerCaps.speed_control} />
                </Form.Item>
              </Form.Item>
              <Form.Item label="音调" tooltip="Mock 模式不支持，保持默认">
                <Form.Item name="pitch" noStyle>
                  <Slider min={0.5} max={1.5} step={0.05} disabled={!providerCaps.pitch_control} />
                </Form.Item>
              </Form.Item>
              <Form.Item label="音量">
                <Form.Item name="volume" noStyle>
                  <Slider min={0} max={2} step={0.05} disabled={!providerCaps.volume_control} />
                </Form.Item>
              </Form.Item>
              <Form.Item label="停顿强度">
                <Form.Item name="pause_strength" noStyle>
                  <Slider min={0.3} max={2} step={0.1} />
                </Form.Item>
              </Form.Item>
              <Form.Item label="情绪">
                <Form.Item name="emotion" noStyle>
                  <Select
                    allowClear
                    placeholder="情绪（可选）"
                    disabled={!providerCaps.emotion}
                    options={[
                      { label: '中性', value: 'neutral' },
                      { label: '温和', value: 'warm' },
                      { label: '有力', value: 'strong' },
                    ]}
                  />
                </Form.Item>
              </Form.Item>
            </Form>

            <Divider style={{ margin: '8px 0' }} />
            <Text type="secondary" style={{ fontSize: 12 }}>
              预计时长：{estimate?.estimated_duration_seconds ?? '-'}s（目标 {estimate?.target_duration_seconds ?? '-'}s）
            </Text>
            {estimate && (
              <div style={{ fontSize: 12, color: '#888', marginTop: 4 }}>
                字数 {estimate.char_count} · 建议语速 {estimate.recommended_speed_min}~{estimate.recommended_speed_max}
              </div>
            )}

            <Button
              type="primary"
              icon={<SoundOutlined />}
              block
              style={{ marginTop: 12 }}
              loading={polling}
              disabled={!selectedShot}
              onClick={handleGenerate}
            >
              生成 / 重新生成配音
            </Button>
            {!providerCaps.pitch_control && (
              <Text type="secondary" style={{ fontSize: 11, display: 'block', marginTop: 6 }}>
                * 当前 Provider 不支持音调/音量/情绪参数，已禁用。
              </Text>
            )}
          </div>
        </div>
      </Card>

      {/* 批量生成确认弹窗 */}
      <Modal
        title="批量生成配音"
        open={batchModalOpen}
        onCancel={() => setBatchModalOpen(false)}
        onOk={handleBatch}
        okText="开始批量生成"
      >
        <Alert
          type="info"
          showIcon
          style={{ marginBottom: 12 }}
          message="批量生成会为每个分镜创建独立任务，单个失败不影响其他分镜。"
        />
        <Form layout="vertical">
          <Form.Item label="时长适配策略">
            <Radio.Group
              value={batchOptions.duration_strategy}
              onChange={(e) => setBatchOptions({ ...batchOptions, duration_strategy: e.target.value })}
            >
              <Radio value="natural">保持自然语速</Radio>
              <Radio value="adjust">合理范围内微调语速</Radio>
            </Radio.Group>
          </Form.Item>
          <Form.Item label="跳过空解说词分镜">
            <Radio.Group
              value={batchOptions.skip_empty}
              onChange={(e) => setBatchOptions({ ...batchOptions, skip_empty: e.target.value })}
            >
              <Radio value={true}>是</Radio>
              <Radio value={false}>否</Radio>
            </Radio.Group>
          </Form.Item>
          <Form.Item label="重新生成已过期的配音">
            <Radio.Group
              value={batchOptions.regenerate_stale}
              onChange={(e) => setBatchOptions({ ...batchOptions, regenerate_stale: e.target.value })}
            >
              <Radio value={true}>是</Radio>
              <Radio value={false}>否</Radio>
            </Radio.Group>
          </Form.Item>
        </Form>
      </Modal>

      {/* 发音词典弹窗 */}
      <PronunciationModal
        open={dictModalOpen}
        projectId={projectId}
        onClose={() => setDictModalOpen(false)}
      />

      {/* 字幕编辑弹窗 */}
      <Modal
        title="编辑字幕时间轴"
        open={subtitleModalOpen}
        onCancel={() => setSubtitleModalOpen(false)}
        width={640}
        footer={null}
      >
        <SubtitleEditor
          subtitles={subtitleData}
          durationMs={(selectedVersion?.actual_duration_seconds || 0) * 1000}
          onSave={async (segs) => {
            try {
              await voiceApi.updateSubtitles(projectId, selectedShot!.id, segs)
              handleSelectShot(selectedShot!)
              setSubtitleModalOpen(false)
            } catch {
              // 已提示
            }
          }}
        />
      </Modal>
    </div>
  )
}

function fmtTime(ms: number) {
  const s = Math.floor(ms / 1000)
  const m = Math.floor(s / 60)
  const r = s % 60
  return `${String(m).padStart(2, '0')}:${String(r).padStart(2, '0')}.${String(ms % 1000).padStart(3, '0')}`
}

function SubtitleEditor({
  subtitles,
  durationMs,
  onSave,
}: {
  subtitles: SubtitleSegment[]
  durationMs: number
  onSave: (segs: { sequence: number; start_ms: number; end_ms: number }[]) => void
}) {
  const [segs, setSegs] = useState(subtitles)
  useEffect(() => setSegs(subtitles), [subtitles])
  const update = (seq: number, key: 'start_ms' | 'end_ms', value: number) => {
    setSegs((prev) => prev.map((s) => (s.sequence === seq ? { ...s, [key]: value } : s)))
  }
  return (
    <div>
      <Alert type="info" showIcon style={{ marginBottom: 8 }} message="点击试听对应时间点；修改后防止重叠与超出音频时长。" />
      <Table
        size="small"
        rowKey="sequence"
        dataSource={segs}
        pagination={false}
        columns={[
          { title: '#', dataIndex: 'sequence', width: 40 },
          {
            title: '开始(ms)',
            width: 110,
            render: (_, s) => (
              <InputNumber
                size="small"
                min={0}
                max={Math.floor(durationMs)}
                value={s.start_ms}
                onChange={(v) => update(s.sequence, 'start_ms', v ?? 0)}
              />
            ),
          },
          {
            title: '结束(ms)',
            width: 110,
            render: (_, s) => (
              <InputNumber
                size="small"
                min={0}
                max={Math.floor(durationMs)}
                value={s.end_ms}
                onChange={(v) => update(s.sequence, 'end_ms', v ?? 0)}
              />
            ),
          },
          { title: '字幕', dataIndex: 'text', ellipsis: true },
        ]}
      />
      <Space style={{ marginTop: 12, width: '100%', justifyContent: 'flex-end' }}>
        <Button onClick={() => setSegs(subtitles)}>重置</Button>
        <Button type="primary" onClick={() => onSave(segs)}>保存</Button>
      </Space>
    </div>
  )
}
