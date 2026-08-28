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
  Progress,
  List,
  Divider,
  App,
  Drawer,
  Table,
  Tooltip,
  Image,
} from 'antd'
import {
  PlusOutlined,
  ReloadOutlined,
  ExportOutlined,
  PlayCircleOutlined,
  PauseCircleOutlined,
  DownloadOutlined,
  ArrowUpOutlined,
  ArrowDownOutlined,
  SoundOutlined,
  PictureOutlined,
  FileTextOutlined,
  SearchOutlined,
  FilterOutlined,
} from '@ant-design/icons'
import { useParams } from 'react-router-dom'
import { assetApi, videoApi, exportApi, downloadVideoFile, downloadVideoSegment, voiceApi } from '../api'
import { withAuthToken } from '../api/client'
import { CollabEntry } from '../components/collab/CollabEntry'
import type { Asset, AudioVersion, VideoProject, VideoSegment, PreflightResult, ExportTask } from '../api/types'
import { useProjectNotifications } from '../components/ProjectNotificationCenter'

const { Title, Text } = Typography

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

const TIME_ADAPTATIONS = [
  { label: '自然速度（推荐）', value: 'natural' },
  { label: '安全变速（0.85x–1.15x）', value: 'safe_stretch' },
  { label: '补帧慢放（RIFE 高质量·严格）', value: 'rife' },
  { label: '循环补足时长', value: 'loop' },
  { label: '冻结尾帧补足', value: 'freeze' },
  { label: '裁剪超出部分', value: 'trim' },
]

const RENDER_STATUS: Record<string, { label: string; color: string }> = {
  pending: { label: '待合成', color: 'default' },
  queued: { label: '排队中', color: 'blue' },
  running: { label: '合成中', color: 'processing' },
  success: { label: '可播放', color: 'success' },
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
  const [mediaAssets, setMediaAssets] = useState<Asset[]>([])
  const [musicAssets, setMusicAssets] = useState<Asset[]>([])
  const [audioVersions, setAudioVersions] = useState<AudioVersion[]>([])
  const [preflight, setPreflight] = useState<PreflightResult | null>(null)
  const [createOpen, setCreateOpen] = useState(false)
  const [exportOpen, setExportOpen] = useState(false)
  const [musicOpen, setMusicOpen] = useState(false)
  const [musicAssetToAdd, setMusicAssetToAdd] = useState<string>()
  const [segmentSearch, setSegmentSearch] = useState('')
  const [segmentFilter, setSegmentFilter] = useState<'all' | 'issues' | 'visual' | 'audio'>('all')
  const [createForm] = Form.useForm()
  const [activeTaskId, setActiveTaskId] = useState<string | null>(null)
  const [activeRenderSegmentId, setActiveRenderSegmentId] = useState<string | null>(null)
  const videoRef = useRef<HTMLVideoElement>(null)
  const segmentPatchTimer = useRef<ReturnType<typeof setTimeout> | null>(null)
  const segmentPollTimer = useRef<ReturnType<typeof setInterval> | null>(null)
  const exportPollTimer = useRef<ReturnType<typeof setInterval> | null>(null)
  const delayedFetchTimer = useRef<ReturnType<typeof setTimeout> | null>(null)
  const [playUrl, setPlayUrl] = useState<string | null>(null)
  const { upsertNotice, removeNotice } = useProjectNotifications()

  useEffect(() => {
    if (!preflight) {
      removeNotice('video:preflight')
      return
    }
    const errors = preflight.issues.filter((issue) => issue.level === 'error').length
    upsertNotice({
      key: 'video:preflight',
      tone: preflight.ok ? 'success' : 'warning',
      title: preflight.ok ? '导出前检查已通过' : `导出前检查发现 ${errors} 个错误`,
      description: preflight.issues.length > 0
        ? preflight.issues.map((issue) => issue.message).join('；')
        : '未发现影响导出的风险，可以继续下一步。',
    })
  }, [preflight, removeNotice, upsertNotice])

  useEffect(() => () => {
    if (segmentPatchTimer.current) clearTimeout(segmentPatchTimer.current)
    if (segmentPollTimer.current) clearInterval(segmentPollTimer.current)
    if (exportPollTimer.current) clearInterval(exportPollTimer.current)
    if (delayedFetchTimer.current) clearTimeout(delayedFetchTimer.current)
    if (videoRef.current) {
      videoRef.current.pause()
      videoRef.current.removeAttribute('src')
      videoRef.current.load()
    }
  }, [])

  const fetchProjects = () => {
    videoApi.list(projectId).then((res) => {
      setProjects(res.data)
      if (!vpId && res.data.length > 0) setVpId(res.data[0].id)
    }).catch(() => {})
  }

  useEffect(fetchProjects, [projectId])

  useEffect(() => {
    assetApi.list(projectId).then((res) => {
      // 视频工程只接受视频素材；图片属于画面制作模块，不进入这里的选择器。
      // 已合成的分段/成片只作为历史版本留档，不作为新的输入素材，避免误选造成工程递归。
      setMediaAssets(res.data.filter((asset) => asset.asset_type === 'video' && asset.source !== 'render'))
    }).catch(() => setMediaAssets([]))
    assetApi.list(projectId, 'audio').then((res) => setMusicAssets(res.data)).catch(() => setMusicAssets([]))
  }, [projectId])

  useEffect(() => {
    const shotId = selectedSeg?.storyboard_shot_id
    if (!shotId) {
      setAudioVersions([])
      return
    }
    voiceApi.versions(projectId, shotId).then((res) => setAudioVersions(res.data)).catch(() => setAudioVersions([]))
  }, [projectId, selectedSeg?.storyboard_shot_id])

  // 尚未合成时，直接预览已选择的视频素材；合成后由分段成片覆盖预览。
  useEffect(() => {
    const player = videoRef.current
    // 待处理/缺失分段只允许预览当前输入素材，绝不能回退到旧的 output_url。
    const sourceUrl = selectedSeg
      ? (selectedSeg.needs_rebuild || selectedSeg.render_status !== 'success'
        ? selectedSeg.visual_url
        : (selectedSeg.output_url || selectedSeg.visual_url))
      : null
    setPlayUrl(sourceUrl || null)
    if (player) {
      player.pause()
      if (sourceUrl) {
        player.src = sourceUrl
        player.load()
      } else {
        player.removeAttribute('src')
        player.load()
      }
    }
  }, [selectedSeg?.id, selectedSeg?.needs_rebuild, selectedSeg?.render_status, selectedSeg?.output_url, selectedSeg?.visual_url])

  useEffect(() => {
    if (!videoRef.current) return
    const isRawPreview = Boolean(selectedSeg && !selectedSeg.output_url && selectedSeg.visual_url && playUrl === selectedSeg.visual_url)
    videoRef.current.playbackRate = isRawPreview && selectedSeg?.visual_playback_speed
      ? Math.max(0.25, Math.min(4, selectedSeg.visual_playback_speed))
      : 1
  }, [playUrl, selectedSeg?.output_url, selectedSeg?.visual_playback_speed])

  const applySegments = (items: VideoSegment[]) => {
    setSegments(items)
    setSelectedSeg((current) => {
      if (!items.length) return null
      return (current && items.find((segment) => segment.id === current.id)) || items[0]
    })
  }

  const fetchVp = (id: string) => {
    if (!id) return
    videoApi.detail(id).then((r) => setVp(r.data)).catch(() => {})
    videoApi.segments(id).then((r) => {
      applySegments(r.data)
    }).catch(() => {})
    videoApi.vpExports(id).then((r) => setExports(r.data)).catch(() => {})
  }

  const pollSegmentRender = (segmentId: string, taskId?: string) => {
    if (!vpId) return
    if (segmentPollTimer.current) clearInterval(segmentPollTimer.current)
    setActiveTaskId(taskId || segmentId)
    setActiveRenderSegmentId(segmentId)
    let attempts = 0
    const timer = setInterval(() => {
      attempts += 1
      videoApi.segments(vpId).then((r) => {
        applySegments(r.data)
        const current = r.data.find((segment) => segment.id === segmentId)
        if (!current || ['success', 'failed', 'skipped'].includes(current.render_status) || attempts > 300) {
          clearInterval(timer)
          segmentPollTimer.current = null
          setActiveTaskId(null)
          setActiveRenderSegmentId(null)
          if (current?.render_status === 'success') message.success('分段合成完成，已保存到素材库')
        }
      }).catch(() => {
        if (attempts > 20) {
          clearInterval(timer)
          segmentPollTimer.current = null
          setActiveTaskId(null)
          setActiveRenderSegmentId(null)
        }
      })
    }, 800)
    segmentPollTimer.current = timer
  }

  useEffect(() => {
    if (vpId) fetchVp(vpId)
  }, [vpId])

  const pollTask = (taskId: string | null) => {
    if (exportPollTimer.current) clearInterval(exportPollTimer.current)
    setActiveTaskId(taskId)
    if (!taskId) return
    const timer = setInterval(() => {
      exportApi.detail(taskId).then((r) => {
        if (r.data.status === 'success' || r.data.status === 'failed' || r.data.status === 'cancelled') {
          clearInterval(timer)
          exportPollTimer.current = null
          setActiveTaskId(null)
          if (r.data.status === 'success') message.success('成片已保存到素材库，可在素材库下载历史版本')
          if (vpId) fetchVp(vpId)
        }
      }).catch(() => {
        clearInterval(timer)
        exportPollTimer.current = null
      })
    }, 1500)
    exportPollTimer.current = timer
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
        fps: values.fps || 24,
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

  const handleRenderOne = async (seg: VideoSegment) => {
    if (!vpId) return
    try {
      const res = await videoApi.renderSegment(vpId, seg.id)
      pollSegmentRender(seg.id, res.data.task_id)
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
        message.info('分段正在合成，稍后自动刷新')
        pollSegmentRender(seg.id, res.data.task_id)
      }
    } catch {
      // 已提示
    }
  }

  const handlePlayPreview = () => {
    if (selectedSeg && (selectedSeg.needs_rebuild || !selectedSeg.output_url)) {
      void handlePreview(selectedSeg)
      return
    }
    void videoRef.current?.play()
  }

  const handleSegmentPatch = async (seg: VideoSegment, payload: Record<string, any>) => {
    if (!vpId) return
    try {
      const res = await videoApi.updateSegment(vpId, seg.id, {
        ...payload,
        base_revision: payload.base_revision ?? seg.revision,
      })
      setSegments((prev) => prev.map((s) => (s.id === seg.id ? res.data : s)))
      setSelectedSeg(res.data)
      if ('visual_asset_id' in payload) {
        setPlayUrl(res.data.visual_url || null)
      }
    } catch {
      // 已提示
    }
  }

  const handleSegmentPatchDebounced = (seg: VideoSegment, payload: Record<string, any>) => {
    const next = { ...seg, ...payload }
    setSegments((prev) => prev.map((item) => (item.id === seg.id ? next : item)))
    setSelectedSeg(next)
    if (segmentPatchTimer.current) clearTimeout(segmentPatchTimer.current)
    segmentPatchTimer.current = setTimeout(() => {
      void handleSegmentPatch(next, payload)
    }, 260)
  }

  const handleMusicUpdate = async (tracks: any[]) => {
    if (!vpId) return
    try {
      const res = await videoApi.update(vpId, { music_tracks: tracks })
      setVp(res.data)
    } catch {
      // 已提示
    }
  }

  const addMusicTrack = () => {
    const asset = musicAssets.find((item) => item.id === musicAssetToAdd)
    if (!asset || !vp) return
    const tracks = [...(vp.music_tracks || [])]
    if (tracks.some((track: any) => track.asset_id === asset.id)) return
    void handleMusicUpdate([...tracks, {
      asset_id: asset.id,
      name: asset.name,
      volume: 0.7,
      fade_in: 1,
      fade_out: 2,
      loop: true,
      authorization_status: 'approved',
    }])
    setMusicAssetToAdd(undefined)
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

  const handleFormalExport = async () => {
    if (!vpId) return
    try {
      const check = await videoApi.preflight(vpId, 'formal')
      setPreflight(check.data)
      if (!check.data.ok) {
        message.error('正式导出前仍有未解决问题，请按提示回到对应分镜处理')
        return
      }
      const res = await videoApi.exportFormal(vpId)
      message.info('正式导出任务已提交，待合成分段会自动处理')
      pollTask(res.data.export_task_id)
      if (delayedFetchTimer.current) clearTimeout(delayedFetchTimer.current)
      delayedFetchTimer.current = setTimeout(() => {
        delayedFetchTimer.current = null
        if (vpId) fetchVp(vpId)
      }, 3000)
    } catch {
      // 已提示
    }
  }

  const totalDuration = useMemo(
    () => segments.reduce((acc, s) => acc + s.duration, 0),
    [segments],
  )

  const latestSuccessfulExport = useMemo(
    () => exports
      .filter((item) => item.status === 'success' && item.output_url)
      .sort((a, b) => String(b.created_at).localeCompare(String(a.created_at)))[0],
    [exports],
  )

  const selectedVisualDuration = selectedSeg?.visual_source_duration
    || mediaAssets.find((asset) => asset.id === selectedSeg?.visual_asset_id)?.duration_seconds
  const selectedVisualAsset = mediaAssets.find((asset) => asset.id === selectedSeg?.visual_asset_id)
  const selectedVisualFirstFrameUrl = selectedVisualAsset
    ? withAuthToken(`/projects/${projectId}/assets/${selectedVisualAsset.id}/first-frame`)
    : null
  const selectedVisualSpeed = selectedVisualDuration && selectedSeg?.duration
    ? selectedVisualDuration / selectedSeg.duration
    : undefined

  const visibleSegments = useMemo(() => {
    const keyword = segmentSearch.trim().toLowerCase()
    return segments.filter((segment) => {
      const matchesSearch = !keyword || `#${segment.sequence} ${segment.shot_title || '分镜'}`.toLowerCase().includes(keyword)
      if (!matchesSearch) return false
      if (segmentFilter === 'issues') return !segment.has_visual || !segment.has_audio || segment.needs_rebuild
      if (segmentFilter === 'visual') return !segment.has_visual
      if (segmentFilter === 'audio') return !segment.has_audio
      return true
    })
  }, [segmentFilter, segmentSearch, segments])

  const activeRenderSegment = activeRenderSegmentId
    ? segments.find((segment) => segment.id === activeRenderSegmentId)
    : segments.find((segment) => ['queued', 'running'].includes(segment.render_status))

  const playSegOutput = (seg: VideoSegment) => {
    const url = seg.needs_rebuild || seg.render_status !== 'success'
      ? seg.visual_url
      : (seg.output_url || seg.visual_url)
    if (url) {
      setPlayUrl(url)
      if (videoRef.current) {
        videoRef.current.src = url
        videoRef.current.load()
        videoRef.current.play()
      }
    } else {
      setPlayUrl(null)
      if (videoRef.current) {
        videoRef.current.pause()
        videoRef.current.removeAttribute('src')
        videoRef.current.load()
      }
    }
  }

  return (
    <div className="video-editor-page">
      <div className="video-editor-toolbar">
        <div className="video-editor-heading">
          <Title level={3} style={{ margin: 0 }}>视频工作区</Title>
          {projectId && vpId && (
            <CollabEntry projectId={projectId} targetType="video_project" targetId={vpId} label="协作与审核" />
          )}
          <Text type="secondary">
            {vp ? `${vp.name} · ${segments.length} 个分段 · ${totalDuration.toFixed(1)}s` : '选择或新建视频工程'}
          </Text>
        </div>
        <Space className="video-editor-toolbar-actions" wrap>
          <Select
            className="video-project-select"
            placeholder="选择视频工程"
            value={vpId || undefined}
            onChange={handleSelectVp}
            options={projects.map((p) => ({ value: p.id, label: `${p.name}（${p.width}×${p.height}@${p.fps}fps）` }))}
          />
          {vp && <Tag color={vp.export_mode === 'formal' ? 'green' : 'orange'}>{vp.export_mode === 'formal' ? '正式工程' : '演示工程'}</Tag>}
          {activeTaskId && <Tag color="processing">{activeRenderSegment ? `合成中 ${activeRenderSegment.render_progress}%` : '正在处理'}</Tag>}
          {vp && <Button onClick={() => setMusicOpen(true)}>背景音乐</Button>}
          {vp && <Button onClick={() => setExportOpen(true)}>导出中心</Button>}
          {latestSuccessfulExport && (
            <Button
              icon={<DownloadOutlined />}
              onClick={() => downloadVideoFile('mp4', latestSuccessfulExport.id).catch(() => message.error('下载成片失败'))}
            >
              下载成片
            </Button>
          )}
          {vp && <Button type="primary" icon={<ExportOutlined />} onClick={handleFormalExport}>导出成片</Button>}
          <Button icon={<PlusOutlined />} onClick={() => setCreateOpen(true)}>新建工程</Button>
        </Space>
      </div>

      {!vp ? (
        <Empty description="请选择或新建视频工程" style={{ marginTop: 60 }} />
      ) : (
        <>
          <div className="video-editor-shell">
          {/* 编辑区 */}
          <Card className="video-workspace-card" styles={{ body: { padding: 0 } }} style={{ marginBottom: 16 }}>
            <div className="video-workspace-layout">
              {/* 左侧：分镜列表 */}
              <div className="video-segment-sidebar">
                <div className="video-segment-sidebar-heading">
                  <Text strong>分段导航</Text>
                  <Text type="secondary">{segments.length} 段</Text>
                </div>
                <Input
                  size="small"
                  allowClear
                  prefix={<SearchOutlined />}
                  placeholder="搜索分段标题"
                  value={segmentSearch}
                  onChange={(event) => setSegmentSearch(event.target.value)}
                  style={{ marginTop: 10 }}
                />
                <Select
                  size="small"
                  value={segmentFilter}
                  onChange={setSegmentFilter}
                  suffixIcon={<FilterOutlined />}
                  options={[
                    { value: 'all', label: '全部分段' },
                    { value: 'issues', label: '待处理' },
                    { value: 'visual', label: '缺画面' },
                    { value: 'audio', label: '缺配音' },
                  ]}
                  style={{ width: '100%', marginTop: 8 }}
                />
                <List
                  size="small"
                  style={{ marginTop: 8 }}
                  dataSource={visibleSegments}
                  renderItem={(s) => {
                    const idx = segments.findIndex((segment) => segment.id === s.id)
                    const st = RENDER_STATUS[s.render_status] || { label: s.render_status, color: 'default' }
                    return (
                      <List.Item
                        onClick={() => {
                          setSelectedSeg(s)
                          playSegOutput(s)
                        }}
                        style={{
                          cursor: 'pointer',
                          background: selectedSeg?.id === s.id ? '#EEF4FC' : undefined,
                          borderRadius: 6,
                        }}
                        actions={[
                          <Space size={0} key="a" className="video-segment-reorder-actions">
                            <Button size="small" type="text" icon={<ArrowUpOutlined />} disabled={idx === 0} onClick={(e) => { e.stopPropagation(); handleReorder(s, -1) }} />
                            <Button size="small" type="text" icon={<ArrowDownOutlined />} disabled={idx === segments.length - 1} onClick={(e) => { e.stopPropagation(); handleReorder(s, 1) }} />
                          </Space>,
                        ]}
                      >
                        <div className="video-segment-item-content">
                          <div className="video-segment-title-row">
                            <b>#{s.sequence} {s.shot_title || '分镜'}</b>
                            <Tag color={st.color} style={{ fontSize: 10, margin: 0 }}>
                              {['queued', 'running'].includes(s.render_status)
                                ? `${st.label} ${s.render_progress}%`
                                : st.label}
                            </Tag>
                          </div>
                          <div className="video-segment-meta-row">
                            <Text type="secondary" style={{ fontSize: 11 }}>{s.duration}s</Text>
                          </div>
                          <div className="video-segment-alerts">
                            {!s.has_visual && <Tag style={{ fontSize: 10, margin: 0 }}>缺画面</Tag>}
                            {!s.has_audio && <Tag style={{ fontSize: 10, margin: 0 }}>缺配音</Tag>}
                            {s.needs_rebuild && <Tag color="warning" style={{ fontSize: 10, margin: 0 }}>设置已变化</Tag>}
                          </div>
                        </div>
                      </List.Item>
                    )
                  }}
                  locale={{ emptyText: '暂无分段，工程会自动同步当前有效分镜' }}
                />
              </div>

              {/* 中间：预览 */}
              <div className="video-preview-panel">
                <div className="video-preview-heading">
                  <div>
                    <Text strong>{selectedSeg ? `#${selectedSeg.sequence} ${selectedSeg.shot_title || '分镜'}` : '视频预览'}</Text>
                    <Text type="secondary">{selectedSeg ? `${selectedSeg.duration}s · ${RENDER_STATUS[selectedSeg.render_status]?.label || selectedSeg.render_status}` : '选择左侧分段开始编辑'}</Text>
                  </div>
                  <Space>
                    <Button size="small" icon={<PlayCircleOutlined />} onClick={handlePlayPreview}>播放</Button>
                    <Button size="small" icon={<PauseCircleOutlined />} onClick={() => videoRef.current?.pause()}>暂停</Button>
                    {vp.output_url && <Button size="small" onClick={() => { setPlayUrl(vp.output_url!); if (videoRef.current) { videoRef.current.src = vp.output_url!; videoRef.current.play() } }}>播放成片</Button>}
                  </Space>
                </div>
                <video
                  ref={videoRef}
                  src={playUrl || undefined}
                  controls
                  className="video-preview-player"
                />
                <div className="video-preview-meta">
                  <Tag>总时长 {totalDuration.toFixed(1)}s</Tag>
                  <Tag>{vp.width}×{vp.height}</Tag>
                  <Tag>{vp.fps}fps</Tag>
                  <Text type="secondary">
                    {selectedSeg && !selectedSeg.output_url && selectedSeg.visual_url
                      ? '当前为原素材预览，播放/预览会按分段时长自动合成'
                      : '当前预览显示已适配时长的分段或已导出的成片'}
                  </Text>
                </div>
              </div>

              {/* 右侧：分段设置 */}
              <div className="video-segment-inspector">
                {selectedSeg ? (
                  <>
                    <Space style={{ width: '100%', justifyContent: 'space-between' }}>
                      <Text strong>分段 #{selectedSeg.sequence}</Text>
                      <Space size={4}>
                        {selectedSeg.render_status === 'success' && selectedSeg.output_url && (
                          <Button
                            size="small"
                            icon={<DownloadOutlined />}
                            title="下载当前已合成的分段 MP4"
                            onClick={() => downloadVideoSegment(vpId, selectedSeg.id, selectedSeg.sequence).catch(() => message.error('下载分段失败'))}
                          >
                            下载视频
                          </Button>
                        )}
                        <Button
                          size="small"
                          icon={<ReloadOutlined />}
                          title="按当前设置重新合成这个分段，不会导出整片"
                          onClick={() => handleRenderOne(selectedSeg)}
                        >
                          重新合成分段
                        </Button>
                      </Space>
                    </Space>
                    {['queued', 'running'].includes(selectedSeg.render_status) && (
                      <>
                        <Progress
                          percent={selectedSeg.render_progress}
                          status="active"
                          size="small"
                          format={(percent) => `合成进度 ${percent}%`}
                          style={{ marginTop: 8 }}
                        />
                        {selectedSeg.time_adaptation === 'rife' && (
                          <Text type="secondary" style={{ display: 'block', fontSize: 12, marginTop: 4 }}>
                            生成中
                          </Text>
                        )}
                      </>
                    )}
                    <Divider style={{ margin: '8px 0' }} />
                    <Space direction="vertical" size={4} style={{ width: '100%' }}>
                      <Text style={{ fontSize: 12 }}>画面素材</Text>
                      <Select
                        size="small"
                        allowClear
                        style={{ width: '100%' }}
                        value={selectedSeg.visual_asset_id || undefined}
                        placeholder="选择视频素材"
                        options={mediaAssets.map((asset) => ({
                          value: asset.id,
                          label: `视频 · ${asset.name}`,
                        }))}
                        optionRender={(option) => {
                          const asset = mediaAssets.find((item) => item.id === option.value)
                          const frameUrl = asset
                            ? withAuthToken(`/projects/${projectId}/assets/${asset.id}/first-frame`)
                            : undefined
                          return (
                            <Space size={8} style={{ minWidth: 0 }}>
                              {frameUrl && (
                                <Image
                                  src={frameUrl}
                                  alt=""
                                  preview={false}
                                  width={56}
                                  height={34}
                                  style={{ objectFit: 'cover', borderRadius: 4, flex: 'none' }}
                                />
                              )}
                              <Text ellipsis={{ tooltip: asset?.name }}>
                                {asset ? `视频 · ${asset.name}` : String(option.label || '')}
                              </Text>
                            </Space>
                          )
                        }}
                        onChange={(v) => handleSegmentPatch(selectedSeg, { visual_asset_id: v || null })}
                      />
                      {selectedVisualAsset && selectedVisualFirstFrameUrl && (
                        <div style={{ marginTop: 8, padding: 8, border: '1px solid #E5E7EB', borderRadius: 8, background: '#FAFBFC' }}>
                          <Text type="secondary" style={{ display: 'block', fontSize: 12, marginBottom: 6 }}>
                            起始帧预览
                          </Text>
                          <Image
                            src={selectedVisualFirstFrameUrl}
                            alt={`${selectedVisualAsset.name} 起始帧`}
                            preview
                            width="100%"
                            height={120}
                            style={{ objectFit: 'cover', borderRadius: 6, display: 'block' }}
                          />
                          <Text ellipsis={{ tooltip: selectedVisualAsset.name }} style={{ display: 'block', marginTop: 6, fontSize: 12 }}>
                            {selectedVisualAsset.name}
                          </Text>
                        </div>
                      )}
                      <Text type="secondary" style={{ fontSize: 11, lineHeight: 1.45 }}>
                        请选择视频素材。
                      </Text>
                      {selectedVisualDuration && selectedVisualSpeed && (
                        <Text type="secondary" style={{ fontSize: 11, lineHeight: 1.45 }}>
                          自动适配时长：原视频 {selectedVisualDuration.toFixed(1)}s → 分段 {selectedSeg.duration.toFixed(1)}s，播放速度 {selectedVisualSpeed.toFixed(2)}x
                        </Text>
                      )}
                      <Text style={{ fontSize: 12 }}>适配模式</Text>
                      <Select size="small" style={{ width: '100%' }} value={selectedSeg.fit_mode} options={FITS}
                        onChange={(v) => handleSegmentPatch(selectedSeg, { fit_mode: v })} />
                      <Text style={{ fontSize: 12 }}>时长适配策略</Text>
                      <Select
                        size="small"
                        style={{ width: '100%' }}
                        value={selectedSeg.time_adaptation || 'natural'}
                        options={TIME_ADAPTATIONS}
                        onChange={(v) => handleSegmentPatch(selectedSeg, { time_adaptation: v })}
                      />
                      <Text type="secondary" style={{ fontSize: 11, lineHeight: 1.45 }}>
                        RIFE 是高质量补帧策略；未安装或运行失败时会明确报错。循环与冻结适合素材偏短的分镜。选择后点击“合成分段”即可验证效果。
                      </Text>
                      <Text style={{ fontSize: 12 }}>转场</Text>
                      <Select size="small" style={{ width: '100%' }} value={selectedSeg.transition_type} options={TRANSITIONS}
                        onChange={(v) => handleSegmentPatch(selectedSeg, { transition_type: v })} />
                      <Text style={{ fontSize: 12 }}>转场时长：{selectedSeg.transition_duration}s</Text>
                      <Slider min={0.1} max={2} step={0.1} value={selectedSeg.transition_duration}
                        onChange={(v) => handleSegmentPatchDebounced(selectedSeg, { transition_duration: v })} />
                      <Text style={{ fontSize: 12 }}>分段时长：{selectedSeg.duration}s</Text>
                      <Text type="secondary" style={{ fontSize: 11, lineHeight: 1.45 }}>
                        默认跟随解说词分镜时长；需要手动调整时先打开“锁定时长”。
                      </Text>
                      <Slider min={1} max={60} step={0.5} value={selectedSeg.duration}
                        disabled={!selectedSeg.is_locked}
                        onChange={(v) => handleSegmentPatchDebounced(selectedSeg, { duration: v })} />
                      <Space style={{ width: '100%', justifyContent: 'space-between' }}>
                        <Text style={{ fontSize: 12 }}>锁定时长</Text>
                        <Switch size="small" checked={selectedSeg.is_locked}
                          onChange={(v) => handleSegmentPatch(selectedSeg, { is_locked: v })} />
                      </Space>
                      <Divider style={{ margin: '4px 0' }} />
                      <Text strong style={{ fontSize: 12 }}>配音</Text>
                      <Select
                        size="small"
                        allowClear
                        style={{ width: '100%' }}
                        value={selectedSeg.audio_version_id || undefined}
                        placeholder={audioVersions.length ? '选择此分镜的配音版本' : '当前分镜暂无配音版本'}
                        options={audioVersions.map((version) => ({
                          value: version.id,
                          label: `V${version.version_number} · ${version.actual_duration_seconds?.toFixed(1) || '—'}s${version.is_selected ? ' · 正式' : ''}`,
                        }))}
                        onChange={(v) => handleSegmentPatch(selectedSeg, { audio_version_id: v || null })}
                      />
                      <Text type="secondary" style={{ fontSize: 11, lineHeight: 1.45 }}>
                        配音版本只作用于当前分段，不会改变分镜的正式版本。
                      </Text>
                      <Space style={{ width: '100%', justifyContent: 'space-between' }}>
                        <Text strong style={{ fontSize: 12 }}>字幕</Text>
                        <Switch size="small" checked={selectedSeg.subtitle_enabled}
                          onChange={(v) => handleSegmentPatch(selectedSeg, { subtitle_enabled: v })} />
                      </Space>
                      <Text style={{ fontSize: 12 }}>音量：{selectedSeg.volume}</Text>
                      <Slider min={0} max={2} step={0.05} value={selectedSeg.volume}
                        onChange={(v) => handleSegmentPatchDebounced(selectedSeg, { volume: v })} />
                    </Space>
                    <Button style={{ marginTop: 8 }} size="small" block icon={<PlayCircleOutlined />} onClick={() => handlePreview(selectedSeg)}>
                      合成并预览该分段
                    </Button>
                  </>
                ) : (
                  <Empty description="选择左侧分段" />
                )}
              </div>
            </div>
          </Card>

          {/* 底部：多轨时间轴 */}
          <Card className="video-timeline-card" size="small" styles={{ body: { padding: 0 } }}>
            <div className="video-timeline-header">
              <Text strong>时间轴</Text>
              <Text type="secondary">{segments.length} 段 / {totalDuration.toFixed(1)}s</Text>
              <Text type="secondary" className="video-timeline-help">点击轨道片段可跳转预览</Text>
            </div>
            <div className="video-timeline-scroller">
              {[
                { key: 'visual', label: '画面', icon: <PictureOutlined /> },
                { key: 'audio', label: '配音', icon: <SoundOutlined /> },
                { key: 'subtitle', label: '字幕', icon: <FileTextOutlined /> },
                { key: 'music', label: '音乐', icon: <SoundOutlined /> },
              ].map((track) => (
                <div className="video-track-row" key={track.key}>
                  <div className="video-track-label">{track.icon}<span>{track.label}</span></div>
                  <div className="video-track-content">
                    {segments.map((s) => (
                      <Tooltip key={`${track.key}-${s.id}`} title={`#${s.sequence} ${s.shot_title || ''} ${s.duration}s`}>
                        <div
                          className={`video-track-clip video-track-clip-${track.key} ${selectedSeg?.id === s.id ? 'is-selected' : ''}`}
                          style={{ width: Math.max(48, s.duration * 8) }}
                          onClick={() => { setSelectedSeg(s); playSegOutput(s) }}
                        >
                          {track.key === 'visual' ? (s.has_visual ? s.sequence : '缺失') : track.key === 'audio' ? (s.has_audio ? '配音' : '缺失') : track.key === 'subtitle' ? (s.subtitle_enabled ? '字幕' : '') : (vp.music_tracks?.length ? '音乐' : '')}
                        </div>
                      </Tooltip>
                    ))}
                  </div>
                </div>
              ))}
            </div>
          </Card>
          </div>

          <Drawer title="背景音乐" open={musicOpen} onClose={() => setMusicOpen(false)} width={520}>
            <Space direction="vertical" size={14} style={{ width: '100%' }}>
              <Text type="secondary">背景音乐独立于分段配音和字幕，导出时按工程时间轴混音。</Text>
              <Space.Compact style={{ width: '100%' }}>
                <Select
                  value={musicAssetToAdd}
                  onChange={setMusicAssetToAdd}
                  placeholder="选择音频素材"
                  options={musicAssets.map((asset) => ({ value: asset.id, label: asset.name }))}
                  style={{ flex: 1 }}
                />
                <Button type="primary" onClick={addMusicTrack} disabled={!musicAssetToAdd}>添加音乐</Button>
              </Space.Compact>
              {(vp.music_tracks || []).length === 0 ? (
                <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="尚未配置背景音乐" />
              ) : (
                (vp.music_tracks || []).map((track: any, index: number) => {
                  const asset = musicAssets.find((item) => item.id === track.asset_id)
                  return (
                    <Card key={`${track.asset_id}-${index}`} size="small" title={track.name || asset?.name || '背景音乐'} extra={(
                      <Button size="small" danger onClick={() => void handleMusicUpdate((vp.music_tracks || []).filter((_: any, i: number) => i !== index))}>移除</Button>
                    )}>
                      <Space direction="vertical" style={{ width: '100%' }} size={4}>
                        <Text type="secondary">音量：{Number(track.volume ?? 0.7).toFixed(2)}</Text>
                        <Slider
                          min={0}
                          max={1.5}
                          step={0.05}
                          value={Number(track.volume ?? 0.7)}
                          onChange={(value) => {
                            const next = [...(vp.music_tracks || [])]
                            next[index] = { ...next[index], volume: value }
                            void handleMusicUpdate(next)
                          }}
                        />
                        <Space style={{ width: '100%', justifyContent: 'space-between' }}>
                          <Text>循环播放</Text>
                          <Switch
                            size="small"
                            checked={track.loop !== false}
                            onChange={(value) => {
                              const next = [...(vp.music_tracks || [])]
                              next[index] = { ...next[index], loop: value }
                              void handleMusicUpdate(next)
                            }}
                          />
                        </Space>
                      </Space>
                    </Card>
                  )
                })
              )}
            </Space>
          </Drawer>

          <Drawer title="导出中心" open={exportOpen} onClose={() => setExportOpen(false)} width={720}>
            <Space direction="vertical" size={16} style={{ width: '100%' }}>
              <div className="video-export-summary">
                <div>
                  <Text strong>正式成片</Text>
                  <Text type="secondary">导出前会自动检查素材，并合成待处理分段。</Text>
                </div>
                <Button type="primary" icon={<ExportOutlined />} onClick={handleFormalExport}>开始导出</Button>
              </div>
              <Table<ExportTask>
                size="small"
                rowKey="id"
                dataSource={exports}
                pagination={false}
                columns={[
                  { title: '模式', dataIndex: 'mode', width: 70, render: (m) => <Tag color={m === 'formal' ? 'red' : 'orange'}>{m === 'formal' ? '正式' : '演示'}</Tag> },
                  { title: '状态', dataIndex: 'status', width: 90, render: (s) => <Tag color={s === 'success' ? 'success' : s === 'failed' ? 'error' : 'processing'}>{s}</Tag> },
                  { title: '进度', dataIndex: 'progress', width: 140, render: (v) => <Progress percent={v} size="small" /> },
                  { title: '时长', dataIndex: 'duration_seconds', width: 80, render: (v) => (v ? `${Math.round(v)}s` : '无') },
                  { title: '错误', dataIndex: 'error_message', ellipsis: true },
                  {
                    title: '操作',
                    width: 260,
                    render: (_, r) => (
                      <Space size={4}>
                        {r.status === 'success' && r.output_url && (
                          <>
                            <Button size="small" icon={<DownloadOutlined />} onClick={() => downloadVideoFile('mp4', r.id)}>下载 MP4</Button>
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
            </Space>
          </Drawer>
        </>
      )}

      {/* 新建视频工程 */}
      <Modal title="新建视频工程" open={createOpen} onOk={handleCreate} onCancel={() => setCreateOpen(false)} width={520}>
        <Form form={createForm} layout="vertical" initialValues={{ name: '投标汇报视频', width: 1920, height: 1080, fps: 24 }}>
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
