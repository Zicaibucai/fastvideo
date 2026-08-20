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
  Switch,
  Upload,
  App,
  Modal,
  Alert,
  Progress,
  Segmented,
  Tooltip,
  Row,
  Col,
  Divider,
  Popconfirm,
  Statistic,
} from 'antd'
import {
  UploadOutlined,
  PictureOutlined,
  ReloadOutlined,
  CheckOutlined,
  HistoryOutlined,
  ExpandOutlined,
  ZoomInOutlined,
  EditOutlined,
  PlayCircleOutlined,
  StopOutlined,
  SafetyOutlined,
} from '@ant-design/icons'
import { useParams } from 'react-router-dom'
import { renderApi, renderPresetApi, shotVisualApi, storyboardApi } from '../api'
import type { RenderPreset, RenderJobTask, RenderVersion, SourceImage, StoryboardShot } from '../api/types'

const { Title, Text, Paragraph } = Typography

const OPERATIONS = [
  { label: '整图渲染', value: 'render' },
  { label: '局部重绘', value: 'inpaint' },
  { label: '16:9 扩图', value: 'outpaint' },
  { label: '清晰度增强', value: 'upscale' },
]

const QUALITY_STATUS_MAP: Record<string, { label: string; color: string }> = {
  passed: { label: '通过', color: 'success' },
  warning: { label: '警告·需审核', color: 'warning' },
  failed: { label: '失败', color: 'error' },
  pending: { label: '待检查', color: 'default' },
}

// 图片 Provider 显示名（用于渲染免责声明，跟随实际 Provider 动态变化）
function imageProviderLabel(provider: string): string {
  switch (provider) {
    case 'seedream':
      return 'Seedream'
    case 'minimax':
      return 'MiniMax'
    case 'openai':
      return 'OpenAI'
    case 'mock':
      return 'AI（演示 Mock）'
    default:
      return 'AI'
  }
}

export default function RenderWorkspace() {
  const { projectId = '' } = useParams()
  const { message } = App.useApp()
  const [shots, setShots] = useState<StoryboardShot[]>([])
  const [presets, setPresets] = useState<RenderPreset[]>([])
  const [sourceImages, setSourceImages] = useState<SourceImage[]>([])
  const [selectedShot, setSelectedShot] = useState<StoryboardShot | null>(null)
  const [selectedSource, setSelectedSource] = useState<string>('')
  const [selectedPreset, setSelectedPreset] = useState<string>('')
  const [operation, setOperation] = useState('render')
  const [form] = Form.useForm()
  const structureStrength = Form.useWatch('structure_strength', form) ?? 85
  const [tasks, setTasks] = useState<RenderJobTask[]>([])
  const [versions, setVersions] = useState<RenderVersion[]>([])
  const [activeTaskId, setActiveTaskId] = useState<string | null>(null)
  const [polling, setPolling] = useState(false)
  const [maskOpen, setMaskOpen] = useState(false)
  const [maskFile, setMaskFile] = useState<File | null>(null)
  const [compareUrls, setCompareUrls] = useState<{ src: string; res: string } | null>(null)
  const [compareOpen, setCompareOpen] = useState(false)
  const [shotFilter, setShotFilter] = useState('all')
  const [providerCaps, setProviderCaps] = useState<Record<string, boolean>>({})
  const [imageProvider, setImageProvider] = useState('')

  // 加载基础数据
  const fetchAll = () => {
    Promise.all([
      storyboardApi.list(projectId),
      renderPresetApi.list(),
      renderApi.listSourceImages(projectId),
      renderApi.listTasks(projectId),
    ])
      .then(([s, p, si, t]) => {
        setShots(s.data)
        setPresets(p.data)
        setSourceImages(si.data)
        setTasks(t.data)
      })
      .catch(() => {})
  }

  useEffect(fetchAll, [projectId])

  // 加载 provider 能力
  useEffect(() => {
    renderApi
      .providers(projectId)
      .then((res) => {
        if (res.data[0]) {
          setProviderCaps(res.data[0].capabilities || {})
          setImageProvider(res.data[0].provider || '')
        }
      })
      .catch(() => {})
  }, [projectId])

  // 渲染任务保存在 RenderJob 表，必须走 renderApi 查询；不能复用通用
  // RenderTask 轮询接口，否则会把 RenderJob ID 误报为“任务不存在”。
  useEffect(() => {
    if (!activeTaskId) return
    let stopped = false
    let timer: ReturnType<typeof setInterval>
    const tick = async () => {
      try {
        const response = await renderApi.getTask(projectId, activeTaskId)
        if (stopped) return
        if (['success', 'failed', 'cancelled'].includes(response.data.status)) {
          clearInterval(timer)
          setActiveTaskId(null)
          setPolling(false)
          fetchAll()
        }
      } catch {
        // 网络瞬时失败时继续下一次轮询；不把正常的渲染任务误报为不存在。
      }
    }
    void tick()
    timer = setInterval(() => void tick(), 1500)
    return () => {
      stopped = true
      clearInterval(timer)
    }
  }, [activeTaskId, projectId])

  const filteredShots = useMemo(() => {
    if (shotFilter === 'missing') return shots.filter((s) => !s.image_asset_id)
    if (shotFilter === 'generating') return shots.filter((s) => s.visual_review_status === 'generating')
    if (shotFilter === 'reviewing') return shots.filter((s) => s.visual_review_status === 'reviewing')
    return shots
  }, [shots, shotFilter])

  const selectedSourceImg = useMemo(
    () => sourceImages.find((s) => s.id === selectedSource) || null,
    [sourceImages, selectedSource],
  )
  const modelSourceImages = useMemo(
    () => sourceImages.filter((image) => image.source === 'model_shot'),
    [sourceImages],
  )

  // 当选择分镜时，自动选择其源图并加载版本
  const handleSelectShot = (shot: StoryboardShot) => {
    setSelectedShot(shot)
    if (shot.source_model_asset_id) {
      setSelectedSource(shot.source_model_asset_id)
    }
    // 加载该分镜相关的渲染版本
    renderApi
      .listVersions(projectId, { shot_id: shot.id })
      .then((res) => setVersions(res.data))
      .catch(() => {})
  }

  const handleUploadSource = async (file: File) => {
    if (!selectedShot) {
      message.warning('请先在左侧选择分镜')
      return false
    }
    try {
      await renderApi.uploadSourceImage(projectId, file, {
        name: file.name,
        source_software: 'Revit',
        camera_angle: '建筑人视',
        storyboard_shot_id: selectedShot.id,
      })
      message.success('模型截图上传成功')
      fetchAll()
    } catch {
      // 拦截器已提示
    }
    return false
  }

  const handleSubmit = async () => {
    const values = await form.validateFields()
    if (!selectedSource) {
      message.warning('请先选择源图')
      return
    }

    const base = {
      source_asset_id: selectedSource,
      storyboard_shot_id: selectedShot?.id,
      preset_id: selectedPreset || null,
      operation_type: operation,
      positive_prompt: values.positive_prompt || '',
      variant_count: values.variant_count || 2,
      structure_strength: values.structure_strength ?? 85,
      creativity: values.creativity ?? 0.5,
      seed: values.seed,
      aspect_ratio: values.aspect_ratio || '16:9',
      idempotency_key: `${Date.now()}`,
    }

    try {
      let res
      if (operation === 'inpaint') {
        if (!maskFile) {
          message.warning('局部重绘需要上传遮罩')
          return
        }
        const maskRes = await renderApi.uploadMask(projectId, maskFile)
        res = await renderApi.inpaint(projectId, {
          source_asset_id: selectedSource,
          storyboard_shot_id: selectedShot?.id,
          mask_asset_id: maskRes.data.asset_id,
          positive_prompt: values.positive_prompt || '',
          variant_count: values.variant_count || 1,
          seed: values.seed,
        })
      } else if (operation === 'outpaint') {
        res = await renderApi.outpaint(projectId, {
          source_asset_id: selectedSource,
          storyboard_shot_id: selectedShot?.id,
          positive_prompt: values.positive_prompt || '',
          target_ratio: values.aspect_ratio || '16:9',
          variant_count: values.variant_count || 1,
          seed: values.seed,
        })
      } else if (operation === 'upscale') {
        res = await renderApi.upscale(projectId, {
          source_asset_id: selectedSource,
          storyboard_shot_id: selectedShot?.id,
          idempotency_key: base.idempotency_key,
        })
      } else {
        res = await renderApi.createTask(projectId, base)
      }
      setActiveTaskId(res.data.id)
      setPolling(true)
      message.success('渲染任务已提交')
      setTimeout(fetchAll, 2000)
    } catch {
      // 拦截器已提示
    }
  }

  const handleSelectVersion = async (version: RenderVersion) => {
    if (!selectedShot) {
      message.warning('请先选择分镜')
      return
    }
    try {
      await shotVisualApi.select(projectId, selectedShot.id, version.id)
      message.success('已设为当前分镜画面')
      fetchAll()
    } catch {
      // 拦截器已提示
    }
  }

  const handleRestoreVersion = async (version: RenderVersion) => {
    if (!selectedShot) return
    try {
      await shotVisualApi.restore(projectId, selectedShot.id, version.id)
      message.success('已恢复历史选择')
      fetchAll()
    } catch {
      // 拦截器已提示
    }
  }

  const handleCompare = (version: RenderVersion) => {
    if (!selectedSourceImg) return
    const resultAsset = versions.find((v) => v.id === version.id)
    const url = resultAsset?.result_asset_id
      ? sourceImages.find((s) => s.id === resultAsset.result_asset_id)?.url
      : null
    setCompareUrls({
      src: selectedSourceImg.url || '',
      res: url || `/files/${resultAsset?.result_asset_id}`,
    })
    setCompareOpen(true)
  }

  const canDo = (op: string) => {
    if (op === 'render') return providerCaps.image_to_image !== false
    if (op === 'inpaint') return providerCaps.inpaint === true
    if (op === 'outpaint') return providerCaps.outpaint === true
    if (op === 'upscale') return providerCaps.upscale === true
    return true
  }

  return (
    <div>
      <div className="page-header">
        <Title level={4} style={{ marginBottom: 4 }}>
          画面制作
        </Title>
        <Text type="secondary">
          模型截图 → AI 渲染 → 版本管理 → 分镜画面绑定
        </Text>
      </div>

      <Alert
        type="info"
        showIcon
        style={{ marginBottom: 16 }}
        message="AI 渲染图仅用于视觉表达。工程尺寸、构件位置、施工顺序和技术参数以原始模型、图纸及施工方案为准。结构一致性检测为辅助检查，不能替代人工审核。"
      />

      <Card styles={{ body: { padding: 0 } }} style={{ height: 'calc(100vh - 240px)' }}>
        <div style={{ display: 'flex', height: '100%' }}>
          {/* 左侧：分镜列表 */}
          <div style={{ width: 280, borderRight: '1px solid #f0f0f0', padding: 12, overflowY: 'auto' }}>
            <Space direction="vertical" style={{ width: '100%' }}>
              <Segmented
                value={shotFilter}
                onChange={(v) => setShotFilter(String(v))}
                options={[
                  { label: '全部', value: 'all' },
                  { label: '缺画面', value: 'missing' },
                  { label: '生成中', value: 'generating' },
                  { label: '审核', value: 'reviewing' },
                ]}
                size="small"
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
                      <Space>
                        <b style={{ fontSize: 13 }}>#{s.sequence} {s.title}</b>
                      </Space>
                      <Space size={4}>
                        {s.image_asset_id ? (
                          <Tag color="green" style={{ fontSize: 11 }}>有画面</Tag>
                        ) : (
                          <Tag style={{ fontSize: 11 }}>缺画面</Tag>
                        )}
                        {s.visual_review_status === 'generating' && (
                          <Tag color="processing" style={{ fontSize: 11 }}>生成中</Tag>
                        )}
                        {s.visual_review_status === 'reviewing' && (
                          <Tag color="warning" style={{ fontSize: 11 }}>待审核</Tag>
                        )}
                      </Space>
                    </Space>
                  </List.Item>
                )}
                locale={{ emptyText: '暂无分镜' }}
              />
            </Space>
          </div>

          {/* 中间：预览 */}
          <div style={{ flex: 1, padding: 16, overflowY: 'auto' }}>
            <Text strong>原图 / 结果对比</Text>
            {selectedSourceImg ? (
              <div style={{ marginTop: 8 }}>
                <img
                  src={selectedSourceImg.url}
                  alt="源图"
                  style={{ maxWidth: '100%', borderRadius: 8, border: '1px solid #f0f0f0' }}
                />
                <Space style={{ marginTop: 8 }}>
                  <Text type="secondary" style={{ fontSize: 12 }}>
                    {selectedSourceImg.width}×{selectedSourceImg.height} · {selectedSourceImg.camera_angle} · {selectedSourceImg.source_software}
                  </Text>
                </Space>
              </div>
            ) : (
              <Empty description="选择源图或上传模型截图" />
            )}

            <Divider />

            <Text strong>生成版本</Text>
            {versions.length === 0 && <Empty description="暂无渲染版本" style={{ marginTop: 12 }} />}
            <div style={{ marginTop: 8, display: 'flex', flexWrap: 'wrap', gap: 8 }}>
              {versions.map((v) => {
                const q = QUALITY_STATUS_MAP[v.quality_status] || { label: v.quality_status, color: 'default' }
                const asset = sourceImages.find((s) => s.id === v.result_asset_id)
                return (
                  <Card key={v.id} size="small" style={{ width: 180 }}>
                    <div style={{ position: 'relative' }}>
                      {asset?.url ? (
                        <img src={asset.url} alt={`V${v.version_number}`} style={{ width: '100%', height: 90, objectFit: 'cover', borderRadius: 4 }} />
                      ) : (
                        <div style={{ width: '100%', height: 90, background: '#f5f5f5', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
                          <Text type="secondary">V{v.version_number}</Text>
                        </div>
                      )}
                      <Tag color={q.color} style={{ position: 'absolute', top: 4, right: 4, fontSize: 10 }}>
                        {q.label}
                      </Tag>
                    </div>
                    <Space style={{ marginTop: 6, width: '100%', justifyContent: 'space-between' }}>
                      <Text strong style={{ fontSize: 12 }}>V{v.version_number}</Text>
                      <Text type="secondary" style={{ fontSize: 10 }}>
                        seed:{v.seed ?? '-'}
                      </Text>
                    </Space>
                    <Space style={{ marginTop: 4 }} wrap>
                      <Button size="small" type="primary" icon={<CheckOutlined />} onClick={() => handleSelectVersion(v)}>
                        设为画面
                      </Button>
                      <Button size="small" icon={<ExpandOutlined />} onClick={() => handleCompare(v)}>
                        对比
                      </Button>
                      <Button size="small" icon={<HistoryOutlined />} onClick={() => handleRestoreVersion(v)}>
                        恢复
                      </Button>
                    </Space>
                  </Card>
                )
              })}
            </div>

            <Divider />

            <Text strong>最近任务</Text>
            {tasks.length === 0 && <Empty description="暂无渲染任务" style={{ marginTop: 12 }} />}
            <List
              size="small"
              dataSource={tasks.slice(0, 5)}
              renderItem={(t) => (
                <List.Item>
                  <Space>
                    <Tag>{OPERATIONS.find((o) => o.value === t.operation_type)?.label || t.operation_type}</Tag>
                    <TaskStatusTag status={t.status} />
                    <Text type="secondary" style={{ fontSize: 12 }}>
                      {t.progress}% · {t.provider}
                    </Text>
                    {t.status === 'failed' && (
                      <Tooltip title={t.error_message}>
                        <Tag color="error" style={{ cursor: 'pointer' }}>失败</Tag>
                      </Tooltip>
                    )}
                    {t.status === 'failed' && (
                      <Button size="small" icon={<ReloadOutlined />} onClick={() => renderApi.retryTask(projectId, t.id).then(() => { setActiveTaskId(t.id); fetchAll() })}>
                        重试
                      </Button>
                    )}
                  </Space>
                </List.Item>
              )}
            />
          </div>

          {/* 右侧：参数表单 */}
          <div style={{ width: 320, borderLeft: '1px solid #f0f0f0', padding: 12, overflowY: 'auto' }}>
            <Text strong>渲染参数</Text>
            <Upload
              accept=".jpg,.jpeg,.png,.webp"
              showUploadList={false}
              beforeUpload={handleUploadSource}
              style={{ marginTop: 8 }}
            >
              <Button icon={<UploadOutlined />} style={{ width: '100%', marginTop: 8 }}>
                上传模型截图
              </Button>
            </Upload>

            <Form form={form} layout="vertical" style={{ marginTop: 8 }} initialValues={{ variant_count: 2, structure_strength: 85, creativity: 0.5, aspect_ratio: '16:9' }}>
              <Form.Item label="源图（仅原始模型截图）">
                <Select
                  value={selectedSource}
                  onChange={setSelectedSource}
                  placeholder="选择模型截图"
                  options={modelSourceImages.map((s) => ({
                    value: s.id,
                    label: `${s.name}（${s.camera_angle || '未标注'}）`,
                  }))}
                />
              </Form.Item>

              <Alert
                type="warning"
                showIcon
                style={{ marginBottom: 12 }}
                message={`${imageProviderLabel(imageProvider)} 参考图生成用于概念效果表达，不是 BIM 几何约束渲染。建筑轮廓、层数、构件与道路关系必须人工复核；正式投标请以 D5、Enscape、Twinmotion 等三维渲染结果为准。`}
              />

              <Form.Item label="渲染风格">
                <Select
                  value={selectedPreset}
                  onChange={setSelectedPreset}
                  placeholder="选择预设"
                  options={presets.map((p) => ({
                    value: p.id,
                    label: `${p.name}${p.is_system ? '' : '（企业）'}`,
                  }))}
                />
              </Form.Item>

              <Form.Item label="操作类型">
                <Select
                  value={operation}
                  onChange={(v) => {
                    setOperation(v)
                    if (v === 'inpaint') setMaskOpen(true)
                  }}
                  options={OPERATIONS.map((o) => ({
                    value: o.value,
                    label: o.label,
                    disabled: !canDo(o.value),
                  }))}
                />
              </Form.Item>

              <Form.Item label="正向提示词" name="positive_prompt">
                <Input.TextArea rows={2} placeholder="画面要求，如：科技蓝投标风格" />
              </Form.Item>

              <Form.Item label="生成数量" name="variant_count">
                <InputNumber min={1} max={4} style={{ width: '100%' }} />
              </Form.Item>

              <Form.Item label="画面比例" name="aspect_ratio">
                <Select
                  options={['16:9', '4:3', '1:1', '9:16'].map((r) => ({ label: r, value: r }))}
                />
              </Form.Item>

              <Form.Item label={`结构保持强度：${structureStrength}`}>
                <Form.Item name="structure_strength" noStyle>
                  <Slider min={0} max={100} />
                </Form.Item>
              </Form.Item>
              {structureStrength < 70 && (
                <Alert type="warning" showIcon message="结构保持强度较低，存在结构变化风险" style={{ marginBottom: 12 }} />
              )}

              <Form.Item label="创意强度" name="creativity">
                <Slider min={0} max={1} step={0.05} />
              </Form.Item>

              <Form.Item label="Seed（可选）" name="seed">
                <InputNumber style={{ width: '100%' }} placeholder="留空自动" />
              </Form.Item>

              <Button type="primary" icon={<PlayCircleOutlined />} block onClick={handleSubmit} loading={polling}>
                开始生成
              </Button>

              {!canDo(operation) && (
                <Alert
                  type="warning"
                  showIcon
                  style={{ marginTop: 8 }}
                  message="当前 Provider 不支持此操作"
                />
              )}
            </Form>
          </div>
        </div>
      </Card>

      {/* 遮罩编辑弹窗 */}
      <Modal
        title="局部重绘 - 上传遮罩"
        open={maskOpen}
        onCancel={() => setMaskOpen(false)}
        onOk={() => {
          setMaskOpen(false)
          message.info('遮罩已选择，请填写局部修改说明后提交')
        }}
        okText="确定"
      >
        <Alert
          type="warning"
          showIcon
          style={{ marginBottom: 12 }}
          message="遮罩需与原图同尺寸的 PNG。白色区域为修改区，黑色为保留区。涉及删除安全设施、修改施工节点或工程结构时必须人工审核。"
        />
        <Upload.Dragger
          accept=".png"
          showUploadList={true}
          beforeUpload={(file) => {
            setMaskFile(file)
            return false
          }}
        >
          <p className="ant-upload-drag-icon"><EditOutlined /></p>
          <p className="ant-upload-text">点击或拖拽遮罩 PNG 文件</p>
        </Upload.Dragger>
      </Modal>

      {/* 对比弹窗 */}
      <Modal
        title="原图 / 结果对比"
        open={compareOpen}
        onCancel={() => setCompareOpen(false)}
        footer={null}
        width={900}
      >
        {compareUrls && (
          <Row gutter={16}>
            <Col span={12}>
              <Text strong>原图</Text>
              <img src={compareUrls.src} alt="原图" style={{ width: '100%', borderRadius: 8, border: '1px solid #f0f0f0' }} />
            </Col>
            <Col span={12}>
              <Text strong>渲染结果</Text>
              <img src={compareUrls.res} alt="结果" style={{ width: '100%', borderRadius: 8, border: '1px solid #f0f0f0' }} />
            </Col>
          </Row>
        )}
      </Modal>
    </div>
  )
}

function TaskStatusTag({ status }: { status: string }) {
  const map: Record<string, { label: string; color: string }> = {
    queued: { label: '排队中', color: 'blue' },
    running: { label: '处理中', color: 'processing' },
    success: { label: '成功', color: 'success' },
    failed: { label: '失败', color: 'error' },
    cancelled: { label: '已取消', color: 'default' },
  }
  const item = map[status] || { label: status, color: 'default' }
  return <Tag color={item.color}>{item.label}</Tag>
}
