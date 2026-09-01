import { useEffect, useMemo, useRef, useState } from 'react'
import {
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
  Upload,
  App,
  Modal,
  Tooltip,
  Row,
  Col,
} from 'antd'
import {
  AppstoreOutlined,
  HistoryOutlined,
  UploadOutlined,
  PictureOutlined,
  ReloadOutlined,
  ExpandOutlined,
  EditOutlined,
  PlayCircleOutlined,
  MoreOutlined,
  SlidersOutlined,
} from '@ant-design/icons'
import { useParams } from 'react-router-dom'
import { CollabEntry } from '../components/collab/CollabEntry'
import { renderApi, renderPresetApi } from '../api'
import { withAuthToken } from '../api/client'
import type { RenderPreset, RenderJobTask, RenderVersion, SourceImage } from '../api/types'

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

export default function RenderWorkspace() {
  const { projectId = '' } = useParams()
  const { message } = App.useApp()
  const [presets, setPresets] = useState<RenderPreset[]>([])
  const [sourceImages, setSourceImages] = useState<SourceImage[]>([])
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
  const [providerCaps, setProviderCaps] = useState<Record<string, boolean>>({})

  // 加载基础数据
  const fetchAll = () => {
    Promise.all([
      renderPresetApi.list(),
      renderApi.listSourceImages(projectId),
      renderApi.listTasks(projectId),
    ])
      .then(([p, si, t]) => {
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

  const selectedSourceImg = useMemo(
    () => sourceImages.find((s) => s.id === selectedSource) || null,
    [sourceImages, selectedSource],
  )
  const modelSourceImages = useMemo(
    () => sourceImages.filter((image) => image.source === 'model_shot'),
    [sourceImages],
  )

  const handleSelectSource = (assetId: string) => {
    setSelectedSource(assetId)
    renderApi
      .listVersions(projectId, { source_asset_id: assetId })
      .then((res) => setVersions(res.data))
      .catch(() => setVersions([]))
  }

  const handleUploadSource = async (file: File) => {
    try {
      await renderApi.uploadSourceImage(projectId, file, {
        name: file.name,
        source_software: 'Revit',
        camera_angle: '建筑人视',
      })
      message.success('模型截图已加入素材库')
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
          mask_asset_id: maskRes.data.asset_id,
          positive_prompt: values.positive_prompt || '',
          variant_count: values.variant_count || 1,
          seed: values.seed,
        })
      } else if (operation === 'outpaint') {
        res = await renderApi.outpaint(projectId, {
          source_asset_id: selectedSource,
          positive_prompt: values.positive_prompt || '',
          target_ratio: values.aspect_ratio || '16:9',
          variant_count: values.variant_count || 1,
          seed: values.seed,
        })
      } else if (operation === 'upscale') {
        res = await renderApi.upscale(projectId, {
          source_asset_id: selectedSource,
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

  const handleCompare = (version: RenderVersion) => {
    if (!selectedSourceImg) return
    const resultAsset = versions.find((v) => v.id === version.id)
    const url = resultAsset?.result_asset_id
      ? sourceImages.find((s) => s.id === resultAsset.result_asset_id)?.url
      : null
    setCompareUrls({
      src: selectedSourceImg.url || '',
      res: url || withAuthToken(`/files/${resultAsset?.result_asset_id}`),
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
      <div className="rw-page-head">
        <div style={{ minWidth: 0 }}>
          <div className="rw-eyebrow">RENDER STUDIO</div>
          <Title level={3} className="rw-title">画面制作</Title>
          <Text type="secondary" style={{ fontSize: 13 }}>
            原始模型/BIM → AI 渲染 → 素材版本管理
          </Text>
        </div>
        {projectId && <CollabEntry projectId={projectId} targetType="project" label="协作" />}
      </div>

      <Card className="workspace-shell render-workspace-shell">
        <div className="workspace-split-layout">
          {/* 左侧：独立源图素材库 */}
          <div className="workspace-sidebar render-sidebar">
            <div className="rw-side-head">
              <span className="rw-section-icon"><PictureOutlined /></span>
              <span className="rw-side-title">源图素材库</span>
              <span className="rw-side-count">{modelSourceImages.length} 张</span>
            </div>
            <Text type="secondary" style={{ display: 'block', marginBottom: 12, fontSize: 11.5 }}>
              这里只管理 BIM / 模型截图，不关联分镜。
            </Text>
            {modelSourceImages.length === 0 ? (
              <div className="rw-empty">
                <span className="rw-empty-icon"><PictureOutlined /></span>
                <span className="rw-empty-title">暂无源图</span>
                <span className="rw-empty-hint">请在右侧上传 BIM / 模型截图</span>
              </div>
            ) : (
              <div className="rw-src-list">
                {modelSourceImages.map((s) => (
                  <div
                    key={s.id}
                    className={`rw-src-card${selectedSource === s.id ? ' is-selected' : ''}`}
                    onClick={() => handleSelectSource(s.id)}
                  >
                    <div className="rw-src-thumb">
                      {s.url ? <img src={s.url} alt={s.name} /> : <PictureOutlined />}
                    </div>
                    <div className="rw-src-body">
                      <span className="rw-src-name" title={s.name}>{s.name}</span>
                      <span className="rw-src-meta">{s.camera_angle || '未标注角度'} · {s.width}×{s.height}</span>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>

          {/* 中间：预览 */}
          <div className="workspace-main render-workspace-main">
            <div className="rw-section">
              <div className="rw-section-head">
                <span className="rw-section-icon"><PictureOutlined /></span>
                <span className="rw-section-title">原图 / 结果对比</span>
                <span className="rw-section-hint">渲染结果独立保存在素材库，视频工程后续按需选用</span>
                {selectedSource && <Tag color="blue" style={{ marginLeft: 8 }}>当前源图已选</Tag>}
              </div>
              {selectedSourceImg ? (
                <div>
                  <div className="render-source-frame">
                    <img src={selectedSourceImg.url} alt="源图" />
                  </div>
                  <div className="rw-source-meta-chips">
                    <span className="rw-meta-chip">{selectedSourceImg.width}×{selectedSourceImg.height}</span>
                    {selectedSourceImg.camera_angle && <span className="rw-meta-chip">{selectedSourceImg.camera_angle}</span>}
                    {selectedSourceImg.source_software && <span className="rw-meta-chip">{selectedSourceImg.source_software}</span>}
                  </div>
                </div>
              ) : (
                <div className="rw-empty">
                  <span className="rw-empty-icon"><PictureOutlined /></span>
                  <span className="rw-empty-title">暂无源图</span>
                  <span className="rw-empty-hint">请在右侧上传模型截图，或从左侧素材库选择</span>
                </div>
              )}
            </div>

            <div className="rw-section">
              <div className="rw-section-head">
                <span className="rw-section-icon"><AppstoreOutlined /></span>
                <span className="rw-section-title">生成版本</span>
                <span className="rw-section-hint">{versions.length > 0 ? `${versions.length} 个版本` : '选择源图后展示其渲染版本'}</span>
              </div>
              {versions.length === 0 ? (
                <div className="rw-empty">
                  <span className="rw-empty-icon"><AppstoreOutlined /></span>
                  <span className="rw-empty-title">暂无渲染版本</span>
                  <span className="rw-empty-hint">在右侧配置参数并点击「开始生成」</span>
                </div>
              ) : (
                <div className="rw-version-grid">
                  {versions.map((v) => {
                    const q = QUALITY_STATUS_MAP[v.quality_status] || { label: v.quality_status, color: 'default' }
                    const asset = sourceImages.find((s) => s.id === v.result_asset_id)
                    return (
                      <div key={v.id} className="rw-version-card">
                        <div className="rw-version-thumb">
                          {asset?.url ? <img src={asset.url} alt={`V${v.version_number}`} /> : <span>V{v.version_number}</span>}
                          <span className={`rw-quality is-${v.quality_status}`}>{q.label}</span>
                        </div>
                        <div className="rw-version-body">
                          <span className="rw-version-name">V{v.version_number}</span>
                          <span className="rw-version-seed">seed: {v.seed ?? '-'}</span>
                        </div>
                        <div className="rw-version-actions">
                          <Button size="small" icon={<ExpandOutlined />} onClick={() => handleCompare(v)}>
                            预览版本
                          </Button>
                          <Dropdown
                            trigger={['click']}
                            menu={{
                              items: [
                                { key: 'compare', icon: <ExpandOutlined />, label: '对比' },
                              ],
                              onClick: ({ key }) => {
                                if (key === 'compare') handleCompare(v)
                              },
                            }}
                          >
                            <Button size="small" icon={<MoreOutlined />} aria-label={`V${v.version_number} 更多操作`} title="更多操作" />
                          </Dropdown>
                        </div>
                      </div>
                    )
                  })}
                </div>
              )}
            </div>

            <div className="rw-section">
              <div className="rw-section-head">
                <span className="rw-section-icon"><HistoryOutlined /></span>
                <span className="rw-section-title">最近任务</span>
                <span className="rw-section-hint">{tasks.length > 0 ? `最近 ${Math.min(tasks.length, 5)} 条` : ''}</span>
              </div>
              {tasks.length === 0 ? (
                <div className="rw-empty">
                  <span className="rw-empty-icon"><HistoryOutlined /></span>
                  <span className="rw-empty-title">暂无渲染任务</span>
                </div>
              ) : (
                <div className="rw-task-list">
                  {tasks.slice(0, 5).map((t) => (
                    <div key={t.id} className="rw-task-row">
                      <span className="rw-task-op">{OPERATIONS.find((o) => o.value === t.operation_type)?.label || t.operation_type}</span>
                      <TaskStatusTag status={t.status} />
                      <span className="rw-task-meta">{t.progress}% · {t.provider}</span>
                      <span className="rw-task-actions">
                        {t.status === 'failed' && (
                          <Space size={6}>
                            <Tooltip title={t.error_message}>
                              <Tag color="error" style={{ cursor: 'pointer', marginInlineEnd: 0 }}>失败原因</Tag>
                            </Tooltip>
                            <Button size="small" icon={<ReloadOutlined />} onClick={() => renderApi.retryTask(projectId, t.id).then(() => { setActiveTaskId(t.id); fetchAll() })}>
                              重试
                            </Button>
                          </Space>
                        )}
                      </span>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>

          {/* 右侧：参数表单 */}
          <div className="workspace-inspector render-inspector">
            <div className="rw-section-head" style={{ marginBottom: 4 }}>
              <span className="rw-section-icon"><SlidersOutlined /></span>
              <span className="rw-section-title">渲染参数</span>
              <span className="rw-section-hint">控制画面风格和生成质量</span>
            </div>
            <Text className="workspace-section-label">素材</Text>
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
                  onChange={handleSelectSource}
                  placeholder="选择模型截图"
                  options={modelSourceImages.map((s) => ({
                    value: s.id,
                    label: `${s.name}（${s.camera_angle || '未标注'}）`,
                  }))}
                />
              </Form.Item>

              <Text className="workspace-section-label">生成方式</Text>

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

              <Text className="workspace-section-label">画面控制</Text>
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
                <Text type="warning" style={{ display: 'block', marginBottom: 12, fontSize: 12 }}>
                  结构保持强度较低，存在结构变化风险
                </Text>
              )}

              <Form.Item label="创意强度" name="creativity">
                <Slider min={0} max={1} step={0.05} />
              </Form.Item>

              <Text className="workspace-section-label">高级参数</Text>
              <Form.Item label="Seed（可选）" name="seed">
                <InputNumber style={{ width: '100%' }} placeholder="留空自动" />
              </Form.Item>

              <Button className="rw-submit" type="primary" icon={<PlayCircleOutlined />} block onClick={handleSubmit} loading={polling}>
                开始生成
              </Button>

              {!canDo(operation) && (
                <Text type="danger" style={{ display: 'block', marginTop: 8, fontSize: 12 }}>
                  当前 Provider 不支持此操作
                </Text>
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
        <Text type="warning" style={{ display: 'block', marginBottom: 12 }}>
          遮罩需与原图同尺寸的 PNG。白色区域为修改区，黑色为保留区。涉及删除安全设施、修改施工节点或工程结构时必须人工审核。
        </Text>
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
              <img src={compareUrls.src} alt="原图" style={{ width: '100%', borderRadius: 8, border: '1px solid var(--border)' }} />
            </Col>
            <Col span={12}>
              <Text strong>渲染结果</Text>
              <img src={compareUrls.res} alt="结果" style={{ width: '100%', borderRadius: 8, border: '1px solid var(--border)' }} />
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
