import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import {
  App,
  Card,
  Typography,
  Space,
  Button,
  Dropdown,
  Tag,
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
  AppstoreOutlined,
  AudioOutlined,
  PlayCircleOutlined,
  CheckOutlined,
  SoundOutlined,
  DeleteOutlined,
  HistoryOutlined,
  BookOutlined,
  ThunderboltOutlined,
  DownloadOutlined,
  FileTextOutlined,
  LinkOutlined,
  MoreOutlined,
  SlidersOutlined,
} from '@ant-design/icons'
import { useNavigate, useParams } from 'react-router-dom'
import { CollabEntry } from '../components/collab/CollabEntry'
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
      <div className="rw-page-head">
        <div style={{ minWidth: 0 }}>
          <div className="rw-eyebrow">VOICE STUDIO</div>
          <Title level={3} className="rw-title">配音制作</Title>
          <Text type="secondary" style={{ fontSize: 13 }}>
            解说词 → 朗读规范化 → AI 配音 → 版本管理 → 字幕生成
          </Text>
        </div>
        {projectId && <CollabEntry projectId={projectId} targetType="project" label="协作" />}
      </div>

      {/* 顶部操作栏 */}
      <div className="vw-toolbar">
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
      </div>

      <Card className="workspace-shell voice-workspace-shell">
        <div className="workspace-split-layout">
          {/* 左侧：分镜列表 */}
          <div className="workspace-sidebar voice-sidebar">
            <div className="rw-side-head">
              <span className="rw-section-icon"><AudioOutlined /></span>
              <span className="rw-side-title">解说词分镜</span>
              <span className="rw-side-count">{filteredShots.length} / {shots.length}</span>
            </div>
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
            {filteredShots.length === 0 ? (
              <div className="rw-empty" style={{ marginTop: 12 }}>
                <span className="rw-empty-icon"><AudioOutlined /></span>
                <span className="rw-empty-title">当前筛选下没有解说词分镜</span>
                <Button size="small" style={{ marginTop: 4 }} onClick={() => navigate(`/project/${projectId}/storyboard`)}>
                  前往解说词系统
                </Button>
              </div>
            ) : (
              <div className="vw-shot-list">
                {filteredShots.map((s) => (
                  <div
                    key={s.id}
                    className={`vw-shot-card${selectedShot?.id === s.id ? ' is-selected' : ''}`}
                    onClick={() => handleSelectShot(s)}
                  >
                    <div className="vw-shot-top">
                      <span className="vw-shot-name">#{s.sequence} {s.title}</span>
                      {s.status === 'ai_generating' ? (
                        <span className="vw-pill is-busy">生成中</span>
                      ) : s.audio_asset_id ? (
                        <span className="vw-pill is-ok">有配音</span>
                      ) : (
                        <span className="vw-pill is-missing">缺配音</span>
                      )}
                    </div>
                    <div className="vw-shot-meta">
                      {(s.narration || '').length}字 · {s.duration_seconds ?? '-'}s
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>

          {/* 中间：配音编辑 */}
          <div className="workspace-main voice-workspace-main">
            {selectedShot ? (
              <>
                <div className="rw-section-head">
                  <span className="rw-section-icon"><FileTextOutlined /></span>
                  <span className="rw-section-title">解说词 #{selectedShot.sequence}</span>
                  <span className="rw-section-hint">先确认朗读文本，再生成和管理配音版本</span>
                  <Space size={6} style={{ marginLeft: 8 }}>
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

                {selectedVersion ? (
                  <>
                    <div className="voice-audio-panel">
                      <div className="voice-audio-player">
                        <audio
                          ref={audioRef}
                          controls
                          src={selectedVersion?.audio_url}
                          style={{ width: '100%' }}
                        />
                      </div>

                      {selectedVersion?.waveform_data?.points && (
                        <div className="voice-waveform">
                          {(selectedVersion.waveform_data.points as number[]).map((p, i) => (
                            <div key={i} style={{ height: Math.max(2, Math.round(p * 40)) }} />
                          ))}
                        </div>
                      )}
                    </div>

                    {/* 目标/实际时长对比 */}
                    <div className="rw-source-meta-chips" style={{ marginTop: 12 }}>
                      <span className="rw-meta-chip">目标 {selectedShot.duration_seconds ?? '-'}s</span>
                      <span className="rw-meta-chip">预计 {estimate?.estimated_duration_seconds ?? '-'}s</span>
                      <span className="rw-meta-chip">实际 {selectedVersion.actual_duration_seconds ?? '-'}s</span>
                      <Tag color={DURATION_STATUS_MAP[selectedVersion.duration_status]?.color} style={{ marginInlineEnd: 0 }}>
                        {DURATION_STATUS_MAP[selectedVersion.duration_status]?.label || selectedVersion.duration_status}
                      </Tag>
                    </div>
                    {estimate?.suggestion && (
                      <Text type="secondary" style={{ display: 'block', marginTop: 8, fontSize: 12 }}>
                        {estimate.suggestion}
                      </Text>
                    )}

                    {/* 字幕句段 */}
                    <div className="rw-section">
                      <div className="rw-section-head" style={{ marginTop: 20 }}>
                        <span className="rw-section-icon"><FileTextOutlined /></span>
                        <span className="rw-section-title">字幕句段</span>
                        <span className="rw-section-hint">{subtitleData.length > 0 ? `${subtitleData.length} 句，点击可跳转试听` : ''}</span>
                        {subtitleData.length > 0 && (
                          <Button size="small" icon={<FileTextOutlined />} style={{ marginLeft: 8 }} onClick={() => setSubtitleModalOpen(true)}>
                            编辑字幕
                          </Button>
                        )}
                      </div>
                      {subtitleData.length > 0 && (
                        <div className="vw-subtitle-list">
                          {subtitleData.map((seg) => (
                            <div key={seg.sequence} className="vw-subtitle-row" onClick={() => seekTo(seg.start_ms)}>
                              <span className="vw-subtitle-time">{fmtTime(seg.start_ms)}</span>
                              <span className="vw-subtitle-text">{seg.text}</span>
                            </div>
                          ))}
                        </div>
                      )}
                    </div>
                  </>
                ) : (
                  <div className="rw-empty" style={{ marginTop: 16, padding: '40px 20px' }}>
                    <span className="rw-empty-icon"><AudioOutlined /></span>
                    <span className="rw-empty-title">暂无配音版本</span>
                    <span className="rw-empty-hint">在右侧选择音色并调整参数，点击「生成配音」；生成后这里会显示音频波形、字幕句段和版本管理</span>
                  </div>
                )}

                {/* 版本列表 */}
                {versions.length > 0 && (
                <div className="rw-section">
                  <div className="rw-section-head" style={{ marginTop: 20 }}>
                    <span className="rw-section-icon"><AppstoreOutlined /></span>
                    <span className="rw-section-title">配音版本</span>
                    <span className="rw-section-hint">{versions.length} 个版本</span>
                  </div>
                  <div className="vw-version-list">
                    {versions.map((v) => (
                      <div key={v.id} className={`vw-version-row${v.is_selected ? ' is-selected' : ''}`}>
                        <span className="vw-version-v">V{v.version_number}</span>
                        <span className="vw-version-meta">{v.actual_duration_seconds ?? '-'}s · 语速 {v.speed}</span>
                        <Tag color={QUALITY_STATUS_MAP[v.quality_status]?.color} style={{ fontSize: 10, marginInlineEnd: 0 }}>
                          {QUALITY_STATUS_MAP[v.quality_status]?.label || v.quality_status}
                        </Tag>
                        <Space size={2}>
                          {v.is_selected && <Tag color="green" style={{ fontSize: 10, margin: 0 }}>正式</Tag>}
                          {v.is_stale && <Tag color="error" style={{ fontSize: 10, margin: 0 }}>过期</Tag>}
                          {v.is_mock && <Tag style={{ fontSize: 10, margin: 0 }}>Mock</Tag>}
                        </Space>
                        <span className="vw-version-actions">
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
                        </span>
                      </div>
                    ))}
                  </div>
                </div>
                )}
              </>
            ) : (
              <div className="rw-empty" style={{ marginTop: 60, padding: '48px 20px' }}>
                <span className="rw-empty-icon"><AudioOutlined /></span>
                <span className="rw-empty-title">请选择左侧分镜</span>
                <span className="rw-empty-hint">选择后即可确认朗读文本并生成配音</span>
              </div>
            )}
          </div>

          {/* 右侧：模板参数 */}
          <div className="workspace-inspector voice-inspector">
            <div className="rw-section-head" style={{ marginBottom: 4 }}>
              <span className="rw-section-icon"><SlidersOutlined /></span>
              <span className="rw-section-title">配音模板</span>
              <span className="rw-section-hint">选择音色并调整朗读参数</span>
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
            <Button
              type="link"
              size="small"
              icon={<LinkOutlined />}
              style={{ padding: 0, marginTop: 6, fontSize: 12 }}
              href="https://www.volcengine.com/product/tts"
              target="_blank"
              rel="noreferrer"
            >
              火山引擎在线试听全部音色
            </Button>

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

            <Divider style={{ margin: '12px 0' }} />
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
              className="rw-submit"
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
