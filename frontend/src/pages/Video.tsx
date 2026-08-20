import { useEffect, useMemo, useRef, useState } from 'react'
import {
  Card,
  Typography,
  Space,
  Button,
  Select,
  Tag,
  Empty,
  Modal,
  Form,
  Input,
  InputNumber,
  Slider,
  Switch,
  Alert,
  Progress,
  List,
  Divider,
  App,
  Popconfirm,
  Drawer,
  Table,
  Tooltip,
} from 'antd'
import {
  PlusOutlined,
  SyncOutlined,
  ThunderboltOutlined,
  ReloadOutlined,
  SafetyOutlined,
  ExportOutlined,
  PlayCircleOutlined,
  PauseCircleOutlined,
  DownloadOutlined,
  DeleteOutlined,
  ArrowUpOutlined,
  ArrowDownOutlined,
  SoundOutlined,
  PictureOutlined,
  FileTextOutlined,
  CheckCircleOutlined,
} from '@ant-design/icons'
import { useParams } from 'react-router-dom'
import { videoApi, exportApi, downloadVideoFile } from '../api'
import type { VideoProject, VideoSegment, PreflightResult, ExportTask } from '../api/types'

const { Title, Text } = Typography

const MOTIONS = [
  { label: '缓慢推进', value: 'zoom_in' },
  { label: '缓慢拉远', value: 'zoom_out' },
  { label: '左右平移', value: 'pan_right' },
  { label: '左平移', value: 'pan_left' },
  { label: '上下平移', value: 'pan_up' },
  { label: '下平移', value: 'pan_down' },
  { label: '保持静止', value: 'static' },
]

const FITS = [
  { label: '裁切填满(cover)', value: 'cover' },
  { label: '完整包含(contain)', value: 'contain' },
  { label: '拉伸填满(fill)', value: 'fill' },
  { label: '模糊背景(blur)', value: 'blur' },
]

const TRANSITIONS = [
  { label: '无转场', value: 'none' },
  { label: '淡入淡出', value: 'fade' },
  { label: '交叉溶解', value: 'crossfade' },
  { label: '黑场', value: 'black' },
  { label: '白场', value: 'white' },
  { label: '左右推移', value: 'slide_right' },
  { label: '科技蓝遮罩', value: 'tech_mask' },
]

const RENDER_STATUS: Record<string, { label: string; color: string }> = {
  pending: { label: '待渲染', color: 'default' },
  queued: { label: '排队中', color: 'blue' },
  running: { label: '渲染中', color: 'processing' },
  success: { label: '成功', color: 'success' },
  failed: { label: '失败', color: 'error' },
  skipped: { label: '已跳过', color: 'default' },
}

export default function Video() {
  const { projectId = '' } = useParams()
  const { message } = App.useApp()
  const [projects, setProjects] = useState<VideoProject[]>([])
  const [vpId, setVpId] = useState<string>('')
  const [vp, setVp] = useState<VideoProject | null>(null)
  const [segments, setSegments] = useState<VideoSegment[]>([])
  const [selectedSeg, setSelectedSeg] = useState<VideoSegment | null>(null)
  const [exports, setExports] = useState<ExportTask[]>([])
  const [preflight, setPreflight] = useState<PreflightResult | null>(null)
  const [createOpen, setCreateOpen] = useState(false)
  const [createForm] = Form.useForm()
  const [busy, setBusy] = useState(false)
  const [activeTaskId, setActiveTaskId] = useState<string | null>(null)
  const videoRef = useRef<HTMLVideoElement>(null)
  const [playUrl, setPlayUrl] = useState<string | null>(null)
  const [settingsOpen, setSettingsOpen] = useState(false)
  const [musicOpen, setMusicOpen] = useState(false)

  const fetchProjects = () => {
    videoApi.list(projectId).then((res) => {
      setProjects(res.data)
      if (!vpId && res.data.length > 0) setVpId(res.data[0].id)
    }).catch(() => {})
  }

  useEffect(fetchProjects, [projectId])

  const fetchVp = (id: string) => {
    if (!id) return
    videoApi.detail(id).then((r) => setVp(r.data)).catch(() => {})
    videoApi.segments(id).then((r) => {
      setSegments(r.data)
      if (!selectedSeg && r.data.length > 0) setSelectedSeg(r.data[0])
    }).catch(() => {})
    videoApi.vpExports(id).then((r) => setExports(r.data)).catch(() => {})
  }

  useEffect(() => {
    if (vpId) fetchVp(vpId)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [vpId])

  const pollTask = (taskId: string | null) => {
    setActiveTaskId(taskId)
    if (!taskId) return
    const timer = setInterval(() => {
      exportApi.detail(taskId).then((r) => {
        if (r.data.status === 'success' || r.data.status === 'failed' || r.data.status === 'cancelled') {
          clearInterval(timer)
          setActiveTaskId(null)
          if (vpId) fetchVp(vpId)
        }
      }).catch(() => clearInterval(timer))
    }, 1500)
  }

  const handleSelectVp = (id: string) => {
    setVpId(id)
    setSelectedSeg(null)
    setPreflight(null)
    fetchVp(id)
  }

  const handleCreate = async () => {
    const values = await createForm.validateFields().catch(() => null)
    if (!values) return
    try {
      const res = await videoApi.create(projectId, {
        name: values.name,
        width: values.width || 1920,
        height: values.height || 1080,
        fps: values.fps || 25,
        open_config: values.open_text ? { text: values.open_text, sub_text: values.open_sub, duration: 2.5 } : undefined,
        close_config: values.close_text ? { text: values.close_text, duration: 2.5 } : undefined,
      })
      message.success('视频工程创建成功')
      setCreateOpen(false)
      fetchProjects()
      setVpId(res.data.id)
    } catch {
      // 已提示
    }
  }

  const handleSync = async () => {
    if (!vpId) return
    setBusy(true)
    try {
      const res = await videoApi.syncStoryboard(vpId)
      message.success(`同步完成：新增 ${res.data.created}，更新 ${res.data.updated}`)
      fetchVp(vpId)
    } catch {
      // 已提示
    } finally {
      setBusy(false)
    }
  }

  const handleRenderAll = async () => {
    if (!vpId) return
    setBusy(true)
    try {
      const res = await videoApi.renderAllSegments(vpId)
      setActiveTaskId(res.data.task_id)
      message.info('分段渲染任务已提交')
      setTimeout(() => { if (vpId) fetchVp(vpId) }, 3000)
    } catch {
      // 已提示
    } finally {
      setBusy(false)
    }
  }

  const handleRenderOne = async (seg: VideoSegment) => {
    if (!vpId) return
    try {
      await videoApi.renderSegment(vpId, seg.id)
      setTimeout(() => { if (vpId) fetchVp(vpId) }, 2500)
    } catch {
      // 已提示
    }
  }

  const handlePreview = async (seg: VideoSegment) => {
    if (!vpId) return
    try {
      const res = await videoApi.previewSegment(vpId, seg.id)
      if (res.data.output_url) {
        setPlayUrl(res.data.output_url)
        if (videoRef.current) {
          videoRef.current.src = res.data.output_url
          videoRef.current.play()
        }
      } else {
        setActiveTaskId(res.data.task_id)
        message.info('分段渲染中，稍后自动刷新')
        setTimeout(() => { if (vpId) fetchVp(vpId) }, 3000)
      }
    } catch {
      // 已提示
    }
  }

  const handleSegmentPatch = async (seg: VideoSegment, payload: Record<string, any>) => {
    if (!vpId) return
    try {
      const res = await videoApi.updateSegment(vpId, seg.id, payload)
      setSegments((prev) => prev.map((s) => (s.id === seg.id ? res.data : s)))
      setSelectedSeg(res.data)
    } catch {
      // 已提示
    }
  }

  const handleReorder = async (seg: VideoSegment, dir: -1 | 1) => {
    if (!vpId) return
    const idx = segments.findIndex((s) => s.id === seg.id)
    const target = idx + dir
    if (target < 0 || target >= segments.length) return
    const next = [...segments]
    ;[next[idx], next[target]] = [next[target], next[idx]]
    try {
      await videoApi.reorderSegments(vpId, next.map((s) => s.id))
      setSegments(next)
    } catch {
      // 已提示
    }
  }

  const handlePreflight = async (mode: 'demo' | 'formal') => {
    if (!vpId) return
    try {
      const res = await videoApi.preflight(vpId, mode)
      setPreflight(res.data)
    } catch {
      // 已提示
    }
  }

  const handleExport = async (mode: 'demo' | 'formal') => {
    if (!vpId) return
    try {
      const res = mode === 'demo' ? await videoApi.exportDemo(vpId) : await videoApi.exportFormal(vpId)
      message.info(`导出任务已提交（${mode === 'demo' ? '演示版' : '正式版'}）`)
      pollTask(res.data.export_task_id)
      setTimeout(() => { if (vpId) fetchVp(vpId) }, 3000)
    } catch {
      // 已提示
    }
  }

  const totalDuration = useMemo(
    () => segments.reduce((acc, s) => acc + s.duration, 0),
    [segments],
  )

  const playSegOutput = (seg: VideoSegment) => {
    if (seg.output_url) {
      setPlayUrl(seg.output_url)
      if (videoRef.current) {
        videoRef.current.src = seg.output_url
        videoRef.current.play()
      }
    }
  }

  return (
    <div>
      <div className="page-header" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <div>
          <Title level={4} style={{ marginBottom: 4 }}>
            视频工作区
          </Title>
          <Text type="secondary">分镜 → 分段渲染 → 转场合成 → 背景音乐 → 正式成片导出</Text>
        </div>
        <Space>
          <Select
            style={{ width: 240 }}
            placeholder="选择视频工程"
            value={vpId || undefined}
            onChange={handleSelectVp}
            options={projects.map((p) => ({ value: p.id, label: `${p.name}（${p.width}×${p.height}@${p.fps}fps）` }))}
          />
          <Button type="primary" icon={<PlusOutlined />} onClick={() => setCreateOpen(true)}>
            新建视频工程
          </Button>
        </Space>
      </div>

      {!vp ? (
        <Empty description="请选择或新建视频工程" style={{ marginTop: 60 }} />
      ) : (
        <>
          {/* 顶部操作栏 */}
          <Space wrap style={{ marginBottom: 12 }}>
            <Button icon={<SyncOutlined />} loading={busy} onClick={handleSync}>同步分镜</Button>
            <Button type="primary" icon={<ThunderboltOutlined />} loading={busy} onClick={handleRenderAll}>
              生成缺失分段
            </Button>
            <Button icon={<SafetyOutlined />} onClick={() => handlePreflight('demo')}>导出前检查(演示)</Button>
            <Button icon={<SafetyOutlined />} onClick={() => handlePreflight('formal')}>导出前检查(正式)</Button>
            <Popconfirm title="演示导出允许 Mock/占位素材，成片标记演示版？" onConfirm={() => handleExport('demo')}>
              <Button icon={<ExportOutlined />}>演示导出</Button>
            </Popconfirm>
            <Popconfirm title="正式导出禁止 Mock/未授权素材？" onConfirm={() => handleExport('formal')}>
              <Button type="primary" danger icon={<ExportOutlined />}>正式导出</Button>
            </Popconfirm>
            {activeTaskId && <Tag color="processing">任务进行中…</Tag>}
          </Space>

          {preflight && (
            <Alert
              type={preflight.ok ? 'success' : 'warning'}
              showIcon
              style={{ marginBottom: 12 }}
              message={`导出前检查（${preflight.mode}）：${preflight.ok ? '通过' : '存在 ' + preflight.issues.filter((i) => i.level === 'error').length + ' 个错误'}`}
              description={
                <Space direction="vertical" size={0}>
                  {preflight.issues.map((i, idx) => (
                    <Text key={idx} type={i.level === 'error' ? 'danger' : 'warning'} style={{ fontSize: 12 }}>
                      [{i.level}] {i.message}
                    </Text>
                  ))}
                  {preflight.issues.length === 0 && <Text type="secondary" style={{ fontSize: 12 }}>未发现问题</Text>}
                </Space>
              }
            />
          )}

          {/* 三栏主体 */}
          <Card styles={{ body: { padding: 0 } }} style={{ marginBottom: 16 }}>
            <div style={{ display: 'flex', minHeight: 460 }}>
              {/* 左侧：分镜列表 */}
              <div style={{ width: 260, borderRight: '1px solid #f0f0f0', padding: 12, overflowY: 'auto', maxHeight: 560 }}>
                <Text strong>分镜分段</Text>
                <List
                  size="small"
                  style={{ marginTop: 8 }}
                  dataSource={segments}
                  renderItem={(s, idx) => {
                    const st = RENDER_STATUS[s.render_status] || { label: s.render_status, color: 'default' }
                    return (
                      <List.Item
                        onClick={() => {
                          setSelectedSeg(s)
                          playSegOutput(s)
                        }}
                        style={{
                          cursor: 'pointer',
                          background: selectedSeg?.id === s.id ? '#e6f4ff' : undefined,
                          borderRadius: 6,
                        }}
                        actions={[
                          <Space size={2} key="a">
                            <Button size="small" type="text" icon={<ArrowUpOutlined />} disabled={idx === 0} onClick={(e) => { e.stopPropagation(); handleReorder(s, -1) }} />
                            <Button size="small" type="text" icon={<ArrowDownOutlined />} disabled={idx === segments.length - 1} onClick={(e) => { e.stopPropagation(); handleReorder(s, 1) }} />
                          </Space>,
                        ]}
                      >
                        <Space direction="vertical" size={0} style={{ width: '100%' }}>
                          <Space>
                            <b style={{ fontSize: 13 }}>#{s.sequence} {s.shot_title || '分镜'}</b>
                            <Tag color={st.color} style={{ fontSize: 10, margin: 0 }}>{st.label}</Tag>
                          </Space>
                          <Space size={4} wrap>
                            <Text type="secondary" style={{ fontSize: 11 }}>{s.duration}s</Text>
                            {!s.has_visual && <Tag style={{ fontSize: 10, margin: 0 }}>缺画面</Tag>}
                            {!s.has_audio && <Tag style={{ fontSize: 10, margin: 0 }}>缺配音</Tag>}
                            {s.needs_rebuild && <Tag color="warning" style={{ fontSize: 10, margin: 0 }}>需重建</Tag>}
                          </Space>
                        </Space>
                      </List.Item>
                    )
                  }}
                  locale={{ emptyText: '暂无分段，点击"同步分镜"' }}
                />
              </div>

              {/* 中间：预览 */}
              <div style={{ flex: 1, padding: 16 }}>
                <Space style={{ width: '100%', justifyContent: 'space-between' }}>
                  <Text strong>预览</Text>
                  <Space>
                    <Button size="small" icon={<PlayCircleOutlined />} onClick={() => videoRef.current?.play()}>播放</Button>
                    <Button size="small" icon={<PauseCircleOutlined />} onClick={() => videoRef.current?.pause()}>暂停</Button>
                    {vp.output_url && <Button size="small" onClick={() => { setPlayUrl(vp.output_url!); if (videoRef.current) { videoRef.current.src = vp.output_url!; videoRef.current.play() } }}>播放成片</Button>}
                  </Space>
                </Space>
                <video
                  ref={videoRef}
                  src={playUrl || undefined}
                  controls
                  style={{ width: '100%', marginTop: 8, background: '#000', borderRadius: 8, maxHeight: 400 }}
                />
                <Space style={{ marginTop: 8 }} wrap>
                  <Tag>总时长 {totalDuration.toFixed(1)}s</Tag>
                  <Tag>{vp.width}×{vp.height}</Tag>
                  <Tag>{vp.fps}fps</Tag>
                  <Tag color={vp.export_mode === 'formal' ? 'red' : 'orange'}>
                    {vp.export_mode === 'formal' ? '正式' : '演示'}模式
                  </Tag>
                </Space>
              </div>

              {/* 右侧：分段设置 */}
              <div style={{ width: 280, borderLeft: '1px solid #f0f0f0', padding: 12, overflowY: 'auto', maxHeight: 560 }}>
                {selectedSeg ? (
                  <>
                    <Space style={{ width: '100%', justifyContent: 'space-between' }}>
                      <Text strong>分段 #{selectedSeg.sequence}</Text>
                      <Button size="small" icon={<ReloadOutlined />} onClick={() => handleRenderOne(selectedSeg)}>渲染</Button>
                    </Space>
                    <Divider style={{ margin: '8px 0' }} />
                    <Space direction="vertical" size={4} style={{ width: '100%' }}>
                      <Text style={{ fontSize: 12 }}>画面运动</Text>
                      <Select size="small" style={{ width: '100%' }} value={selectedSeg.visual_motion} options={MOTIONS}
                        onChange={(v) => handleSegmentPatch(selectedSeg, { visual_motion: v })} />
                      <Text style={{ fontSize: 12 }}>适配模式</Text>
                      <Select size="small" style={{ width: '100%' }} value={selectedSeg.fit_mode} options={FITS}
                        onChange={(v) => handleSegmentPatch(selectedSeg, { fit_mode: v })} />
                      <Text style={{ fontSize: 12 }}>转场</Text>
                      <Select size="small" style={{ width: '100%' }} value={selectedSeg.transition_type} options={TRANSITIONS}
                        onChange={(v) => handleSegmentPatch(selectedSeg, { transition_type: v })} />
                      <Text style={{ fontSize: 12 }}>转场时长：{selectedSeg.transition_duration}s</Text>
                      <Slider min={0.1} max={2} step={0.1} value={selectedSeg.transition_duration}
                        onChange={(v) => handleSegmentPatch(selectedSeg, { transition_duration: v })} />
                      <Text style={{ fontSize: 12 }}>分段时长：{selectedSeg.duration}s</Text>
                      <Slider min={1} max={60} step={0.5} value={selectedSeg.duration}
                        onChange={(v) => handleSegmentPatch(selectedSeg, { duration: v })} />
                      <Space>
                        <Text style={{ fontSize: 12 }}>锁定时长</Text>
                        <Switch size="small" checked={selectedSeg.is_locked}
                          onChange={(v) => handleSegmentPatch(selectedSeg, { is_locked: v })} />
                        <Text style={{ fontSize: 12 }}>字幕</Text>
                        <Switch size="small" checked={selectedSeg.subtitle_enabled}
                          onChange={(v) => handleSegmentPatch(selectedSeg, { subtitle_enabled: v })} />
                      </Space>
                      <Text style={{ fontSize: 12 }}>音量：{selectedSeg.volume}</Text>
                      <Slider min={0} max={2} step={0.05} value={selectedSeg.volume}
                        onChange={(v) => handleSegmentPatch(selectedSeg, { volume: v })} />
                    </Space>
                    <Button style={{ marginTop: 8 }} size="small" block icon={<PlayCircleOutlined />} onClick={() => handlePreview(selectedSeg)}>
                      预览该分段
                    </Button>
                  </>
                ) : (
                  <Empty description="选择左侧分段" />
                )}
              </div>
            </div>
          </Card>

          {/* 底部：时间轴 */}
          <Card size="small" title={`多轨时间轴（${segments.length} 段 / ${totalDuration.toFixed(1)}s）`}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 4, height: 48 }}>
              {segments.map((s) => (
                <Tooltip key={s.id} title={`#${s.sequence} ${s.shot_title || ''} ${s.duration}s ${s.render_status}`}>
                  <div
                    onClick={() => { setSelectedSeg(s); playSegOutput(s) }}
                    style={{
                      width: Math.max(40, s.duration * 8),
                      height: 36,
                      background: s.render_status === 'success' ? '#1677ff' : s.render_status === 'failed' ? '#ff4d4f' : '#d9d9d9',
                      color: '#fff',
                      borderRadius: 4,
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'center',
                      fontSize: 11,
                      cursor: 'pointer',
                      border: selectedSeg?.id === s.id ? '2px solid #000' : 'none',
                    }}
                  >
                    {s.sequence}
                  </div>
                </Tooltip>
              ))}
            </div>
            <Space style={{ marginTop: 8 }} size={8}>
              <Tag icon={<PictureOutlined />}>画面轨</Tag>
              <Tag icon={<SoundOutlined />}>配音轨</Tag>
              <Tag icon={<FileTextOutlined />}>字幕轨</Tag>
              <Tag>音乐轨</Tag>
              <Tag>Logo轨</Tag>
              <Tag>片头片尾</Tag>
            </Space>
          </Card>

          {/* 导出记录 */}
          <Card size="small" title="导出记录" style={{ marginTop: 16 }}>
            <Table<ExportTask>
              size="small"
              rowKey="id"
              dataSource={exports}
              pagination={false}
              columns={[
                { title: '模式', dataIndex: 'mode', width: 70, render: (m) => <Tag color={m === 'formal' ? 'red' : 'orange'}>{m === 'formal' ? '正式' : '演示'}</Tag> },
                { title: '状态', dataIndex: 'status', width: 90, render: (s) => <Tag color={s === 'success' ? 'success' : s === 'failed' ? 'error' : 'processing'}>{s}</Tag> },
                { title: '进度', dataIndex: 'progress', width: 140, render: (v) => <Progress percent={v} size="small" /> },
                { title: '时长', dataIndex: 'duration_seconds', width: 80, render: (v) => (v ? `${Math.round(v)}s` : '—') },
                { title: '错误', dataIndex: 'error_message', ellipsis: true },
                {
                  title: '操作',
                  width: 260,
                  render: (_, r) => (
                    <Space size={4}>
                      {r.status === 'success' && r.output_url && (
                        <>
                          <Button size="small" icon={<DownloadOutlined />} onClick={() => downloadVideoFile('mp4', r.id)}>MP4</Button>
                          {r.srt_url && <Button size="small" icon={<DownloadOutlined />} onClick={() => downloadVideoFile('srt', r.id)}>SRT</Button>}
                          {r.report_url && <Button size="small" icon={<DownloadOutlined />} onClick={() => downloadVideoFile('report', r.id)}>报告</Button>}
                        </>
                      )}
                      {(r.status === 'failed' || r.status === 'cancelled') && (
                        <Button size="small" icon={<ReloadOutlined />} onClick={() => exportApi.retry(r.id).then(() => pollTask(r.id))}>重试</Button>
                      )}
                      {(r.status === 'queued' || r.status === 'running') && (
                        <Button size="small" danger onClick={() => exportApi.cancel(r.id)}>取消</Button>
                      )}
                    </Space>
                  ),
                },
              ]}
              locale={{ emptyText: '暂无导出记录' }}
            />
          </Card>
        </>
      )}

      {/* 新建视频工程 */}
      <Modal title="新建视频工程" open={createOpen} onOk={handleCreate} onCancel={() => setCreateOpen(false)} width={520}>
        <Form form={createForm} layout="vertical" initialValues={{ name: '投标汇报视频', width: 1920, height: 1080, fps: 25 }}>
          <Form.Item name="name" label="工程名称" rules={[{ required: true, message: '请输入名称' }]}>
            <Input placeholder="例如：XX项目投标汇报视频" />
          </Form.Item>
          <Space size={16}>
            <Form.Item name="width" label="宽度">
              <InputNumber min={1280} max={7680} />
            </Form.Item>
            <Form.Item name="height" label="高度">
              <InputNumber min={720} max={4320} />
            </Form.Item>
            <Form.Item name="fps" label="帧率">
              <Select options={[{ value: 24, label: '24fps' }, { value: 25, label: '25fps' }, { value: 30, label: '30fps' }]} style={{ width: 90 }} />
            </Form.Item>
          </Space>
          <Form.Item name="open_text" label="片头文字（可选）">
            <Input placeholder="如：XX项目投标汇报" />
          </Form.Item>
          <Form.Item name="open_sub" label="片头副标题（可选）">
            <Input placeholder="如：东部新城科创中心" />
          </Form.Item>
          <Form.Item name="close_text" label="片尾文字（可选）">
            <Input placeholder="如：匠心筑造 · 诚信履约" />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  )
}
