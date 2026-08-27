import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import {
  App,
  Card,
  Typography,
  Space,
  Button,
  Dropdown,
  List,
  Tag,
  Empty,
  Form,
  Input,
  Select,
  InputNumber,
  Slider,
  Modal,
  Progress,
  Segmented,
  Table,
  Divider,
  Badge,
  Radio,
  Tooltip,
} from 'antd'
import {
  PlayCircleOutlined,
  CheckOutlined,
  SoundOutlined,
  DeleteOutlined,
  HistoryOutlined,
  BookOutlined,
  ThunderboltOutlined,
  DownloadOutlined,
  FileTextOutlined,
  MoreOutlined,
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
  const { message } = App.useApp()
  const [shots, setShots] = useState<StoryboardShot[]>([])
  const [selectedShotId, setSelectedShotId] = useState<string | null>(null)
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
  const [normalizedTextEdited, setNormalizedTextEdited] = useState(false)
  const detailRequestRef = useRef(0)

  // 配音工作区不保存另一份解说词；始终以当前项目的解说词分镜为唯一数据源。
  const fetchScripts = useCallback(async () => {
    if (!projectId) return
    const response = await storyboardApi.list(projectId)
    const nextShots = response.data
    setShots(nextShots)
    setSelectedShotId((current) => {
      if (current && nextShots.some((shot) => shot.id === current)) return current
      return nextShots[0]?.id || null
    })
  }, [projectId])

  // 加载项目解说词、配音模板与 Provider 能力。
  const fetchAll = useCallback(() => {
    Promise.all([
      storyboardApi.list(projectId),
      voiceTemplateApi.list(),
      voiceProviderApi.list(),
    ])
      .then(([s, t, p]) => {
        setShots(s.data)
        setSelectedShotId((current) => {
          if (current && s.data.some((shot) => shot.id === current)) return current
          return s.data[0]?.id || null
        })
        setTemplates(t.data)
        if (p.data[0]) {
          setProvider(p.data[0].provider)
          setProviderCaps(p.data[0].capabilities || {})
        }
      })
      .catch(() => {})
  }, [projectId])

  useEffect(() => {
    setSelectedShotId(null)
    fetchAll()
  }, [fetchAll])

  // 从解说词页返回、切换标签页或后台生成完成后，自动拉取最新文稿。
  useEffect(() => {
    const syncWhenVisible = () => {
      if (document.visibilityState === 'visible') fetchScripts().catch(() => {})
    }
    window.addEventListener('focus', syncWhenVisible)
    document.addEventListener('visibilitychange', syncWhenVisible)
    const timer = window.setInterval(syncWhenVisible, 15000)
    return () => {
      window.removeEventListener('focus', syncWhenVisible)
      document.removeEventListener('visibilitychange', syncWhenVisible)
      window.clearInterval(timer)
    }
  }, [fetchScripts])

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
      voiceApi.jobs(projectId).then((res) => {
        setRecentJobs(res.data)
        if (res.data.some((job) => ['queued', 'running', 'retrying'].includes(job.status))) {
          fetchScripts().catch(() => {})
        }
      }).catch(() => {})
    }
    load()
    const timer = setInterval(load, 5000)
    return () => clearInterval(timer)
  }, [fetchScripts, projectId])

  const filteredShots = useMemo(() => {
    if (shotFilter === 'missing') return shots.filter((s) => !s.audio_asset_id)
    if (shotFilter === 'generating') return shots.filter((s) => s.status === 'ai_generating')
    if (shotFilter === 'needs_adjust') {
      return shots.filter((s) =>
        s.audio_is_stale ||
        s.audio_duration_status === 'script_adjustment_required' ||
        s.audio_quality_status === 'warning' ||
        s.audio_quality_status === 'failed',
      )
    }
    return shots
  }, [shots, shotFilter])

  const selectedVersion = useMemo(
    () => versions.find((v) => v.is_selected) || null,
    [versions],
  )

  const selectedShot = useMemo(
    () => shots.find((shot) => shot.id === selectedShotId) || null,
    [selectedShotId, shots],
  )

  const loadShotDetails = useCallback(async (shot: StoryboardShot) => {
    const requestId = ++detailRequestRef.current
    setVersions([])
    setSubtitleData([])
    setEstimate(null)
    setNormalizedTextEdited(false)
    const [versionsResult, estimateResult, subtitlesResult] = await Promise.allSettled([
      voiceApi.versions(projectId, shot.id),
      voiceApi.estimate(projectId, shot.id, selectedTemplateId || undefined),
      voiceApi.subtitles(projectId, shot.id),
    ])
    if (requestId !== detailRequestRef.current) return
    if (versionsResult.status === 'fulfilled') setVersions(versionsResult.value.data)
    if (estimateResult.status === 'fulfilled') setEstimate(estimateResult.value.data)
    if (subtitlesResult.status === 'fulfilled') setSubtitleData(subtitlesResult.value.data.subtitle_data)
  }, [projectId, selectedTemplateId])

  useEffect(() => {
    if (!selectedShot) {
      setVersions([])
      setSubtitleData([])
      setEstimate(null)
      return
    }
    loadShotDetails(selectedShot).catch(() => {})
  }, [loadShotDetails, selectedShot?.id, selectedShot?.narration, selectedShot?.narration_hash])

  const handleSelectShot = (shot: StoryboardShot) => setSelectedShotId(shot.id)

  const handleGenerate = async () => {
    if (!selectedShot) {
      return
    }
    const values = await form.validateFields().catch(() => null)
    if (!values) return
    // 生成前再读一次解说词，防止在另一个页面刚保存的新稿被旧页面覆盖。
    const latestResponse = await storyboardApi.list(projectId).catch(() => null)
    if (!latestResponse) return
    const latestShots = latestResponse.data
    const latestShot = latestShots.find((shot) => shot.id === selectedShot.id)
    setShots(latestShots)
    if (!latestShot) {
      message.warning('该分镜已从解说词系统移除，请重新选择。')
      return
    }
    if ((latestShot.narration || '') !== (selectedShot.narration || '')) {
      message.warning('解说词刚刚有更新，已同步最新内容，请确认后再生成配音。')
      return
    }
    const payload: Record<string, any> = {
      shot_id: selectedShot.id,
      voice_template_id: selectedTemplateId || null,
      speed: values.speed ?? 1.0,
      pitch: values.pitch ?? 1.0,
      volume: values.volume ?? 1.0,
      pause_strength: values.pause_strength ?? 1.0,
      emotion: values.emotion || undefined,
      normalized_text_override: normalizedTextEdited ? estimate?.normalized_text || undefined : undefined,
      output_formats: ['wav', 'mp3'],
      idempotency_key: `gen-${Date.now()}`,
    }
    try {
      await voiceApi.generate(projectId, payload)
      setPolling(true)
      setTimeout(() => {
        loadShotDetails(selectedShot).catch(() => {})
        fetchScripts().catch(() => {})
      }, 2500)
    } catch {
      // 拦截器已提示
    }
  }

  const handleSelectVersion = async (v: AudioVersion) => {
    if (!selectedShot) return
    try {
      await voiceApi.selectVersion(projectId, selectedShot.id, v.id)
      loadShotDetails(selectedShot).catch(() => {})
    } catch {
      // 已提示
    }
  }

  const handleDeleteVersion = async (v: AudioVersion) => {
    if (!selectedShot) return
    try {
      await voiceApi.deleteVersion(projectId, selectedShot.id, v.id)
      loadShotDetails(selectedShot).catch(() => {})
    } catch {
      // 已提示
    }
  }

  const handleRestoreVersion = async (v: AudioVersion) => {
    if (!selectedShot) return
    try {
      await voiceApi.restoreVersion(projectId, selectedShot.id, v.id)
      loadShotDetails(selectedShot).catch(() => {})
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
      setTimeout(() => fetchScripts().catch(() => {}), 3000)
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
      <div className="page-header workspace-page-header">
        <div className="page-heading">
          <Title level={3} style={{ marginBottom: 6 }}>
            配音制作
          </Title>
          <Text type="secondary" className="page-description">
            解说词 → 朗读规范化 → AI 配音 → 版本管理 → 字幕生成
          </Text>
        </div>
      </div>

      {/* 顶部操作栏 */}
      <Space wrap className="workspace-toolbar">
        <Button type="primary" icon={<ThunderboltOutlined />} onClick={() => setBatchModalOpen(true)}>
          批量生成配音
        </Button>
        <Button icon={<BookOutlined />} onClick={() => setDictModalOpen(true)}>
          发音词典
        </Button>
        <Button icon={<FileTextOutlined />} onClick={() => navigate(`/project/${projectId}/voice-templates`)}>
          配音模板管理
        </Button>
        <Dropdown
          menu={{
            items: [
              { key: 'wav', icon: <DownloadOutlined />, label: '导出全部 WAV' },
              { key: 'mp3', icon: <DownloadOutlined />, label: '导出全部 MP3' },
              { key: 'srt', icon: <FileTextOutlined />, label: '导出项目 SRT' },
            ],
            onClick: ({ key }) => downloadVoiceFile(projectId, key as 'wav' | 'mp3' | 'srt'),
          }}
        >
          <Button icon={<DownloadOutlined />}>导出</Button>
        </Dropdown>
        <span className="toolbar-spacer" />
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

      <Card className="workspace-shell voice-workspace-shell">
        <div className="workspace-split-layout">
          {/* 左侧：分镜列表 */}
          <div className="workspace-sidebar voice-sidebar">
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
                    className={`workspace-list-item ${selectedShot?.id === s.id ? 'is-selected' : ''}`}
                    onClick={() => handleSelectShot(s)}
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
                locale={{
                  emptyText: (
                    <Empty description="当前筛选下没有解说词分镜">
                      <Button size="small" onClick={() => navigate(`/project/${projectId}/storyboard`)}>
                        前往解说词系统
                      </Button>
                    </Empty>
                  ),
                }}
              />
            </Space>
          </div>

          {/* 中间：配音编辑 */}
          <div className="workspace-main voice-workspace-main">
            {selectedShot ? (
              <>
                <div className="workspace-panel-heading">
                  <div>
                    <Text strong>解说词 #{selectedShot.sequence}</Text>
                    <Text type="secondary">先确认朗读文本，再生成和管理配音版本</Text>
                  </div>
                  <Space size={6}>
                    {selectedVersion?.is_mock && <Tag color="orange">Mock Audio</Tag>}
                    {selectedVersion?.is_stale && <Tag color="error">解说词已修改，需要重新生成配音</Tag>}
                  </Space>
                </div>
                <Text className="voice-read-label">原始解说词</Text>
                <Paragraph className="voice-script-preview">
                  {selectedShot.narration || '（无解说词）'}
                </Paragraph>

                <div className="voice-read-section">
                  <Text className="voice-read-label">规范化朗读文本</Text>
                  <Text className="voice-read-help">可人工修改，仅影响本次配音，不会改变原解说词。</Text>
                  <Input.TextArea
                    rows={2}
                    value={estimate?.normalized_text || ''}
                    style={{ marginTop: 8 }}
                    placeholder="等待估算结果"
                    onChange={(e) => {
                      setNormalizedTextEdited(true)
                      setEstimate((prev) => (prev ? { ...prev, normalized_text: e.target.value } : prev))
                    }}
                  />
                </div>

                <div className="voice-audio-panel">
                  <div className="voice-audio-player">
                    <audio
                      ref={audioRef}
                      controls
                      src={selectedVersion?.audio_url}
                      style={{ width: '100%' }}
                    />
                  </div>

                  {selectedVersion?.waveform_data?.points ? (
                    <div className="voice-waveform">
                      {(selectedVersion.waveform_data.points as number[]).map((p, i) => (
                        <div key={i} style={{ height: Math.max(2, Math.round(p * 40)) }} />
                      ))}
                    </div>
                  ) : (
                    <Empty description="生成配音后显示波形" style={{ margin: '8px 0' }} />
                  )}
                </div>

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
                  <Text type="secondary" style={{ display: 'block', marginTop: 8, fontSize: 12 }}>
                    {estimate.suggestion}
                  </Text>
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
                  className="workspace-data-table"
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
                          <Dropdown
                            trigger={['click']}
                            menu={{
                              items: [
                                { key: 'restore', icon: <HistoryOutlined />, label: '恢复版本' },
                                { type: 'divider' },
                                { key: 'delete', danger: true, icon: <DeleteOutlined />, label: '删除版本' },
                              ],
                              onClick: ({ key }) => {
                                if (key === 'restore') handleRestoreVersion(v)
                                if (key === 'delete') {
                                  Modal.confirm({
                                    title: '删除该版本？',
                                    content: '删除后无法恢复，请确认仍要继续。',
                                    okText: '删除',
                                    okType: 'danger',
                                    cancelText: '取消',
                                    onOk: () => handleDeleteVersion(v),
                                  })
                                }
                              },
                            }}
                          >
                            <Button size="small" icon={<MoreOutlined />} aria-label={`V${v.version_number} 更多操作`} title="更多操作" />
                          </Dropdown>
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
          <div className="workspace-inspector voice-inspector">
            <div className="workspace-panel-heading workspace-panel-heading-compact">
              <div>
                <Text strong>配音模板</Text>
                <Text type="secondary">选择音色并调整朗读参数</Text>
              </div>
            </div>
            <Select
              style={{ width: '100%', marginTop: 8 }}
              placeholder="选择配音模板"
              value={selectedTemplateId || undefined}
              onChange={setSelectedTemplateId}
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
              <Text className="workspace-section-label">音色参数</Text>
              <Form.Item label={`语速：${selectedSpeed}${!providerCaps.speed_control ? '（当前 Provider 不支持）' : ''}`}>
                <Form.Item name="speed" noStyle>
                  <Slider min={0.85} max={1.2} step={0.01} disabled={!providerCaps.speed_control} />
                </Form.Item>
              </Form.Item>
              <Form.Item
                label={
                  <Tooltip title={!providerCaps.pitch_control ? '当前 Provider 不提供音调控制，已保持默认值。' : ''}>
                    音调{!providerCaps.pitch_control ? '（当前 Provider 不支持）' : ''}
                  </Tooltip>
                }
              >
                <Form.Item name="pitch" noStyle>
                  <Slider min={0.5} max={1.5} step={0.05} disabled={!providerCaps.pitch_control} />
                </Form.Item>
              </Form.Item>
              <Form.Item
                label={
                  <Tooltip title={!providerCaps.volume_control ? '当前 Provider 不提供音量控制，已保持默认值。' : ''}>
                    音量{!providerCaps.volume_control ? '（当前 Provider 不支持）' : ''}
                  </Tooltip>
                }
              >
                <Form.Item name="volume" noStyle>
                  <Slider min={0} max={2} step={0.05} disabled={!providerCaps.volume_control} />
                </Form.Item>
              </Form.Item>
              <Form.Item label="停顿强度">
                <Form.Item name="pause_strength" noStyle>
                  <Slider min={0.3} max={2} step={0.1} />
                </Form.Item>
              </Form.Item>
              <Form.Item
                label={
                  <Tooltip title={!providerCaps.emotion ? '当前 Provider 不提供情绪控制，已保持默认值。' : ''}>
                    情绪{!providerCaps.emotion ? '（当前 Provider 不支持）' : ''}
                  </Tooltip>
                }
              >
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
              <div className="voice-estimate-note">
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
              生成配音
            </Button>
            {!selectedShot && <Text className="voice-inspector-help">请先在左侧选择一个分镜。</Text>}
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
        <Text type="secondary" style={{ display: 'block', marginBottom: 12 }}>
          批量生成会为每个分镜创建独立任务，单个失败不影响其他分镜。
        </Text>
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
              loadShotDetails(selectedShot!).catch(() => {})
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
      <Text type="secondary" style={{ display: 'block', marginBottom: 8, fontSize: 12 }}>
        点击试听对应时间点，修改后防止重叠与超出音频时长。
      </Text>
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
