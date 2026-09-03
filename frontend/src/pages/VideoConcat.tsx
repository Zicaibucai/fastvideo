import { useEffect, useMemo, useRef, useState } from 'react'
import {
  Typography,
  Space,
  Button,
  Select,
  Tag,
  Empty,
  Input,
  Slider,
  List,
  App,
  Table,
  Tooltip,
  Upload,
  Progress,
  Image,
} from 'antd'
import {
  PlusOutlined,
  ReloadOutlined,
  ExportOutlined,
  DownloadOutlined,
  ArrowUpOutlined,
  ArrowDownOutlined,
  DeleteOutlined,
  SearchOutlined,
  UploadOutlined,
  PlayCircleOutlined,
  PauseCircleOutlined,
} from '@ant-design/icons'
import { useParams } from 'react-router-dom'
import { assetApi, concatApi, downloadConcatFile } from '../api'
import { withAuthToken } from '../api/client'
import type { Asset, ConcatTask } from '../api/types'

const { Title, Text } = Typography

/** 与合成分镜保持一致的转场选项（作用于当前片段与下一片段之间） */
const TRANSITIONS = [
  { label: '无转场', value: 'none' },
  { label: '淡入淡出', value: 'fade' },
  { label: '交叉溶解', value: 'crossfade' },
  { label: '黑场', value: 'black' },
  { label: '白场', value: 'white' },
  { label: '左右推移', value: 'slide_right' },
  { label: '科技蓝遮罩', value: 'tech_mask' },
]

const RESOLUTIONS = [
  { label: '1920 × 1080', value: '1920x1080' },
  { label: '1280 × 720', value: '1280x720' },
]

const SOURCE_LABELS: Record<string, string> = {
  upload: '上传',
  render: '合成',
}

interface SeqItem {
  asset: Asset
  transition_type: string
  transition_duration: number
}

function assetUrl(asset: Asset): string | null {
  if (asset.file_key) return withAuthToken(`/files/${asset.file_key}`)
  return asset.url ? withAuthToken(asset.url) : null
}

export default function VideoConcat() {
  const { projectId = '' } = useParams()
  const { message } = App.useApp()
  const [assets, setAssets] = useState<Asset[]>([])
  const [assetSearch, setAssetSearch] = useState('')
  const [sequence, setSequence] = useState<SeqItem[]>([])
  const [tasks, setTasks] = useState<ConcatTask[]>([])
  const [previewUrl, setPreviewUrl] = useState<string | null>(null)
  const [name, setName] = useState('')
  const [resolution, setResolution] = useState('1920x1080')
  const [fps, setFps] = useState(25)
  // 统一转场设置：作为新加片段的默认值，也可一键应用到全部边界
  const [globalTransition, setGlobalTransition] = useState('none')
  const [globalTransitionDuration, setGlobalTransitionDuration] = useState(0.5)
  const [exporting, setExporting] = useState(false)
  const [uploading, setUploading] = useState(false)
  const videoRef = useRef<HTMLVideoElement>(null)
  const pollTimer = useRef<ReturnType<typeof setInterval> | null>(null)

  useEffect(() => () => {
    if (pollTimer.current) clearInterval(pollTimer.current)
  }, [])

  // 预览切换时重新加载并自动播放；清空时释放播放器
  useEffect(() => {
    const player = videoRef.current
    if (!player) return
    if (previewUrl) {
      player.src = previewUrl
      player.load()
      player.play().catch(() => {})
    } else {
      player.pause()
      player.removeAttribute('src')
      player.load()
    }
  }, [previewUrl])

  const fetchAssets = () => {
    // 拼接接受所有视频素材：上传的剪映成品，以及本系统合成分段/成片（source=render）
    assetApi.list(projectId, 'video').then((res) => setAssets(res.data)).catch(() => setAssets([]))
  }

  const fetchTasks = () => {
    concatApi.list(projectId).then((res) => setTasks(res.data)).catch(() => {})
  }

  useEffect(() => {
    if (!projectId) return
    fetchAssets()
    fetchTasks()
  }, [projectId])

  const pollTask = (taskId: string) => {
    if (pollTimer.current) clearInterval(pollTimer.current)
    setExporting(true)
    const timer = setInterval(() => {
      concatApi.detail(taskId).then((r) => {
        if (r.data.status === 'success' || r.data.status === 'failed' || r.data.status === 'cancelled') {
          clearInterval(timer)
          pollTimer.current = null
          setExporting(false)
          if (r.data.status === 'success') {
            message.success('拼接完成，成片已存入素材库')
            if (r.data.output_url) setPreviewUrl(withAuthToken(r.data.output_url))
            fetchAssets()
          } else if (r.data.status === 'failed') {
            message.error(`拼接失败：${r.data.error_message || '未知错误'}`)
          }
          fetchTasks()
        }
      }).catch(() => {
        clearInterval(timer)
        pollTimer.current = null
        setExporting(false)
      })
    }, 1500)
    pollTimer.current = timer
  }

  const addToSequence = (asset: Asset) => {
    if (sequence.some((item) => item.asset.id === asset.id)) {
      message.info('该片段已在拼接序列中')
      return
    }
    setSequence((prev) => [...prev, {
      asset,
      transition_type: globalTransition,
      transition_duration: globalTransitionDuration,
    }])
  }

  const applyGlobalTransition = () => {
    setSequence((prev) => prev.map((item, index) => (
      index < prev.length - 1
        ? { ...item, transition_type: globalTransition, transition_duration: globalTransitionDuration }
        : item
    )))
    message.success('已将统一转场应用到全部片段边界')
  }

  const moveItem = (index: number, dir: -1 | 1) => {
    const target = index + dir
    if (target < 0 || target >= sequence.length) return
    setSequence((prev) => {
      const next = [...prev]
      ;[next[index], next[target]] = [next[target], next[index]]
      return next
    })
  }

  const patchItem = (index: number, payload: Partial<SeqItem>) => {
    setSequence((prev) => prev.map((item, i) => (i === index ? { ...item, ...payload } : item)))
  }

  const totalDuration = useMemo(() => {
    const raw = sequence.reduce((acc, item) => acc + (item.asset.duration_seconds || 0), 0)
    const transitions = sequence.slice(0, -1).reduce(
      (acc, item) => acc + (item.transition_type === 'none' ? 0.1 : item.transition_duration),
      0,
    )
    return Math.max(0, raw - transitions)
  }, [sequence])

  const handleUpload = async (file: File) => {
    setUploading(true)
    try {
      await assetApi.upload(projectId, file, file.name)
      message.success('上传成功')
      fetchAssets()
    } catch {
      // 已提示
    } finally {
      setUploading(false)
    }
    return false
  }

  const handleExport = async () => {
    if (sequence.length < 2) return
    const [width, height] = resolution.split('x').map(Number)
    try {
      const res = await concatApi.create(projectId, {
        name: name.trim() || undefined,
        width,
        height,
        fps,
        items: sequence.map((item) => ({
          asset_id: item.asset.id,
          transition_type: item.transition_type,
          transition_duration: item.transition_duration,
        })),
      })
      message.info('拼接任务已提交')
      fetchTasks()
      if (!['success', 'failed'].includes(res.data.status)) {
        pollTask(res.data.id)
      } else {
        fetchTasks()
        if (res.data.status === 'success') fetchAssets()
      }
    } catch {
      // 已提示
    }
  }

  const visibleAssets = useMemo(() => {
    const keyword = assetSearch.trim().toLowerCase()
    return assets.filter((asset) => !keyword || asset.name.toLowerCase().includes(keyword))
  }, [assetSearch, assets])

  const latestSuccess = useMemo(
    () => tasks.find((task) => task.status === 'success' && task.output_url),
    [tasks],
  )

  return (
    <div className="video-editor-page">
      <div className="video-editor-toolbar">
        <div className="video-editor-heading">
          <Title level={3} style={{ margin: 0 }}>分镜拼接</Title>
          <Text type="secondary">
            把剪映做好的片段或本系统合成的分段按顺序拼接成整片，分辨率和帧率自动统一
          </Text>
        </div>
        <Space className="video-editor-toolbar-actions" wrap>
          {exporting && <Tag color="processing">拼接中…</Tag>}
          {latestSuccess && (
            <Button
              icon={<DownloadOutlined />}
              onClick={() => downloadConcatFile(latestSuccess).catch(() => message.error('下载失败'))}
            >
              下载最近成片
            </Button>
          )}
          <Button
            type="primary"
            icon={<ExportOutlined />}
            disabled={sequence.length < 2 || exporting}
            onClick={handleExport}
          >
            导出拼接（{sequence.length} 段）
          </Button>
        </Space>
      </div>

      <div className="video-editor-shell">
        <div className="video-workspace-layout">
          {/* 左侧：素材选择 */}
          <div className="video-segment-sidebar video-concat-sidebar">
            <div className="video-segment-sidebar-heading">
              <Text strong>视频素材</Text>
              <Text type="secondary">{assets.length} 个</Text>
            </div>
            <Upload showUploadList={false} accept="video/*" beforeUpload={handleUpload}>
              <Button block icon={<UploadOutlined />} loading={uploading} style={{ marginTop: 10 }}>
                上传视频
              </Button>
            </Upload>
            <Input
              size="small"
              allowClear
              prefix={<SearchOutlined />}
              placeholder="搜索素材名称"
              value={assetSearch}
              onChange={(event) => setAssetSearch(event.target.value)}
              style={{ marginTop: 8 }}
            />
            <List
              size="small"
              style={{ marginTop: 8 }}
              dataSource={visibleAssets}
              renderItem={(asset) => {
                const inSequence = sequence.some((item) => item.asset.id === asset.id)
                const frameUrl = withAuthToken(`/projects/${projectId}/assets/${asset.id}/first-frame`)
                return (
                  <List.Item
                    style={{
                      cursor: 'pointer',
                      borderRadius: 6,
                      background: previewUrl === assetUrl(asset) ? '#EEF4FC' : undefined,
                    }}
                    onClick={() => {
                      const url = assetUrl(asset)
                      if (url) setPreviewUrl(url)
                    }}
                  >
                    <div style={{ display: 'flex', alignItems: 'center', gap: 8, width: '100%', minWidth: 0 }}>
                      <Image
                        src={frameUrl}
                        alt=""
                        preview={false}
                        width={72}
                        height={42}
                        style={{ objectFit: 'cover', borderRadius: 4, flex: 'none', background: '#15191f' }}
                      />
                      <div style={{ flex: 1, minWidth: 0 }}>
                        <div className="video-segment-title-row">
                          <b>{asset.name}</b>
                          <Tag style={{ fontSize: 10, margin: 0 }}>{SOURCE_LABELS[asset.source] || asset.source}</Tag>
                        </div>
                        <div className="video-segment-meta-row">
                          <Text type="secondary" style={{ fontSize: 11 }}>
                            {asset.duration_seconds ? `${asset.duration_seconds.toFixed(1)}s` : '时长未知'}
                            {asset.width && asset.height ? ` · ${asset.width}×${asset.height}` : ''}
                          </Text>
                        </div>
                      </div>
                      <Button
                        size="small"
                        icon={<PlusOutlined />}
                        disabled={inSequence}
                        title="加入拼接序列"
                        onClick={(e) => { e.stopPropagation(); addToSequence(asset) }}
                      >
                        加入
                      </Button>
                    </div>
                  </List.Item>
                )
              }}
              locale={{ emptyText: '暂无视频素材，点击上方按钮上传' }}
            />
          </div>

          {/* 中间：预览与导出设置 */}
          <div className="video-preview-panel">
            <div className="video-preview-heading">
              <div>
                <Text strong>预览</Text>
                <Text type="secondary">点击左侧素材预览；导出后在此播放成片</Text>
              </div>
              <Space>
                <Button size="small" icon={<PlayCircleOutlined />} onClick={() => videoRef.current?.play()}>播放</Button>
                <Button size="small" icon={<PauseCircleOutlined />} onClick={() => videoRef.current?.pause()}>暂停</Button>
              </Space>
            </div>
            <video ref={videoRef} controls className="video-preview-player" />
            <div className="video-preview-meta" style={{ display: 'block' }}>
              <Space direction="vertical" size={8} style={{ width: '100%' }}>
                <Space wrap>
                  <Tag>预计总时长 {totalDuration.toFixed(1)}s</Tag>
                  <Tag>{resolution.replace('x', '×')}</Tag>
                  <Tag>{fps}fps</Tag>
                </Space>
                <Input
                  placeholder="成片名称（可选，默认带时间戳）"
                  value={name}
                  onChange={(event) => setName(event.target.value)}
                />
                <Space wrap>
                  <Text style={{ fontSize: 12 }}>分辨率</Text>
                  <Select size="small" value={resolution} onChange={setResolution} options={RESOLUTIONS} style={{ width: 140 }} />
                  <Text style={{ fontSize: 12 }}>帧率</Text>
                  <Select
                    size="small"
                    value={fps}
                    onChange={setFps}
                    options={[{ value: 24, label: '24fps' }, { value: 25, label: '25fps' }, { value: 30, label: '30fps' }]}
                    style={{ width: 90 }}
                  />
                </Space>
                <Space wrap align="center">
                  <Text style={{ fontSize: 12 }}>统一转场</Text>
                  <Select
                    size="small"
                    value={globalTransition}
                    onChange={setGlobalTransition}
                    options={TRANSITIONS}
                    style={{ width: 120 }}
                  />
                  {globalTransition !== 'none' && (
                    <>
                      <Slider
                        style={{ width: 110 }}
                        min={0.1}
                        max={2}
                        step={0.1}
                        value={globalTransitionDuration}
                        onChange={setGlobalTransitionDuration}
                      />
                      <Text style={{ fontSize: 12 }}>{globalTransitionDuration.toFixed(1)}s</Text>
                    </>
                  )}
                  <Button size="small" disabled={sequence.length < 2} onClick={applyGlobalTransition}>
                    应用到全部
                  </Button>
                </Space>
                <Text type="secondary" style={{ fontSize: 11, lineHeight: 1.45 }}>
                  所有片段会统一缩放/补边到目标分辨率并统一帧率；无音轨的片段自动补静音。
                  统一转场作为新加片段的默认转场，单个边界仍可在右侧序列里单独调整。
                </Text>
              </Space>
            </div>
          </div>

          {/* 右侧：拼接序列 */}
          <div className="video-segment-inspector">
            <Text strong>拼接序列（{sequence.length} 段）</Text>
            {sequence.length === 0 ? (
              <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="从左侧素材加入至少两段视频" style={{ marginTop: 24 }} />
            ) : (
              <List
                size="small"
                style={{ marginTop: 8 }}
                dataSource={sequence}
                renderItem={(item, index) => (
                  <List.Item style={{ display: 'block', padding: '8px 0' }}>
                    <Space style={{ width: '100%', justifyContent: 'space-between' }}>
                      <Text ellipsis={{ tooltip: item.asset.name }} style={{ maxWidth: 150, fontSize: 12 }}>
                        {index + 1}. {item.asset.name}
                      </Text>
                      <Space size={0}>
                        <Button size="small" type="text" icon={<ArrowUpOutlined />} disabled={index === 0} onClick={() => moveItem(index, -1)} />
                        <Button size="small" type="text" icon={<ArrowDownOutlined />} disabled={index === sequence.length - 1} onClick={() => moveItem(index, 1)} />
                        <Button size="small" type="text" danger icon={<DeleteOutlined />} onClick={() => setSequence((prev) => prev.filter((_, i) => i !== index))} />
                      </Space>
                    </Space>
                    <Text type="secondary" style={{ fontSize: 11 }}>
                      {item.asset.duration_seconds ? `${item.asset.duration_seconds.toFixed(1)}s` : '时长未知'}
                    </Text>
                    {index < sequence.length - 1 && (
                      <div style={{ marginTop: 4, padding: 6, background: '#F6F8FA', borderRadius: 6 }}>
                        <Space style={{ width: '100%', justifyContent: 'space-between' }}>
                          <Text style={{ fontSize: 11 }}>到下一段的转场</Text>
                          <Select
                            size="small"
                            value={item.transition_type}
                            options={TRANSITIONS}
                            style={{ width: 110 }}
                            onChange={(v) => patchItem(index, { transition_type: v })}
                          />
                        </Space>
                        {item.transition_type !== 'none' && (
                          <>
                            <Text style={{ fontSize: 11 }}>转场时长：{item.transition_duration}s</Text>
                            <Slider
                              min={0.1}
                              max={2}
                              step={0.1}
                              value={item.transition_duration}
                              onChange={(v) => patchItem(index, { transition_duration: v })}
                            />
                          </>
                        )}
                      </div>
                    )}
                  </List.Item>
                )}
              />
            )}
          </div>
        </div>

        {/* 底部：拼接记录 */}
        <div style={{ marginTop: 16 }}>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '8px 0' }}>
            <Text strong>拼接记录</Text>
            <Button size="small" icon={<ReloadOutlined />} onClick={fetchTasks}>刷新</Button>
          </div>
          <Table<ConcatTask>
            size="small"
            rowKey="id"
            dataSource={tasks}
            pagination={false}
            columns={[
              { title: '名称', dataIndex: ['params', 'name'], ellipsis: true, render: (v) => v || '分镜拼接' },
              {
                title: '状态', dataIndex: 'status', width: 100,
                render: (s) => <Tag color={s === 'success' ? 'success' : s === 'failed' ? 'error' : s === 'cancelled' ? 'default' : 'processing'}>{s}</Tag>,
              },
              { title: '进度', dataIndex: 'progress', width: 130, render: (v, r) => ['queued', 'running'].includes(r.status) ? <Progress percent={v} size="small" /> : `${v}%` },
              { title: '时长', dataIndex: 'duration_seconds', width: 80, render: (v) => (v ? `${Math.round(v)}s` : '—') },
              {
                title: '错误', dataIndex: 'error_message', ellipsis: true,
                render: (v) => (v ? <Tooltip title={v}><Text type="danger" style={{ fontSize: 12 }}>{v}</Text></Tooltip> : '—'),
              },
              { title: '时间', dataIndex: 'created_at', width: 160, render: (v) => String(v).replace('T', ' ').slice(0, 19) },
              {
                title: '操作',
                width: 220,
                render: (_, r) => (
                  <Space size={4}>
                    {r.status === 'success' && r.output_url && (
                      <Button size="small" icon={<DownloadOutlined />} onClick={() => downloadConcatFile(r).catch(() => message.error('下载失败'))}>下载</Button>
                    )}
                    {(r.status === 'failed' || r.status === 'cancelled') && (
                      <Button size="small" icon={<ReloadOutlined />} onClick={() => concatApi.retry(r.id).then((res) => { if (!['success', 'failed'].includes(res.data.status)) pollTask(r.id); else fetchTasks() })}>重试</Button>
                    )}
                    {(r.status === 'queued' || r.status === 'running') && (
                      <Button size="small" danger onClick={() => concatApi.cancel(r.id).then(fetchTasks)}>取消</Button>
                    )}
                  </Space>
                ),
              },
            ]}
            locale={{ emptyText: '暂无拼接记录' }}
          />
        </div>
      </div>
    </div>
  )
}
