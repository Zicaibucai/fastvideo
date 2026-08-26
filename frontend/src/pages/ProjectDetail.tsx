import { useEffect, useState } from 'react'
import {
  Card,
  Row,
  Col,
  Statistic,
  Typography,
  Table,
  Tag,
  Button,
  Space,
  App,
  Popconfirm,
  Progress,
  Upload,
  Input,
  InputNumber,
  DatePicker,
} from 'antd'
import {
  UploadOutlined,
  FileTextOutlined,
  ReloadOutlined,
  DeleteOutlined,
  EditOutlined,
  CheckOutlined,
  CloseOutlined,
  PlayCircleOutlined,
  VideoCameraOutlined,
  BookOutlined,
  DatabaseOutlined,
  BgColorsOutlined,
} from '@ant-design/icons'
import { useParams, useNavigate } from 'react-router-dom'
import { documentApi, projectApi } from '../api'
import type { Project, SourceDocument } from '../api/types'
import dayjs from 'dayjs'

const { Title, Text } = Typography

const DOC_TYPE_LABEL: Record<string, string> = {
  tender: '招标文件',
  scoring: '评分办法',
  construction: '施工组织设计',
  profile: '项目概况',
  schedule: '总进度计划',
  special: '专项施工方案',
  qualification: '企业资信及案例',
  other: '其他资料',
}

const NORMAL_UPLOAD_LIMIT = 30 * 1024 * 1024
const RESUMABLE_UPLOAD_LIMIT = 1024 * 1024 * 1024
const ACCEPTED_EXTENSIONS = ['.pdf', '.docx', '.txt']

const PROJECT_FLOW_STEPS = [
  {
    title: '上传并解析资料',
    description: '先上传招标文件、施工资料和评分办法，系统会自动识别关键信息。',
  },
  {
    title: '核对项目参数',
    description: '检查建筑面积、投标截止、工期和招标人，必要时可直接修改。',
  },
  {
    title: '生成解说词与分镜',
    description: '根据已确认的资料生成讲解文案和镜头结构，作为后续制作底稿。',
  },
  {
    title: '制作画面与配音',
    description: '按分镜整理画面、素材和声音，完成视频内容的制作。',
  },
  {
    title: '创建视频工程',
    description: '汇总脚本、画面和配音，进入工程编排并输出最终视频。',
  },
]

async function sha256Hex(blob: Blob): Promise<string> {
  const buffer = await blob.arrayBuffer()
  const hash = await crypto.subtle.digest('SHA-256', buffer)
  return Array.from(new Uint8Array(hash))
    .map((b) => b.toString(16).padStart(2, '0'))
    .join('')
}

export default function ProjectDetail() {
  const { projectId = '' } = useParams()
  const navigate = useNavigate()
  const { message } = App.useApp()
  const [project, setProject] = useState<Project | null>(null)
  const [docs, setDocs] = useState<SourceDocument[]>([])
  const [loading, setLoading] = useState(false)
  const [uploading, setUploading] = useState(false)
  const [uploadProgress, setUploadProgress] = useState<number | null>(null)
  const [editingSummary, setEditingSummary] = useState(false)
  const [savingSummary, setSavingSummary] = useState(false)
  const [summaryDraft, setSummaryDraft] = useState<{
    bid_area: number | null
    bid_deadline: string
    construction_period: string
    bidder_name: string
  }>({
    bid_area: null,
    bid_deadline: '',
    construction_period: '',
    bidder_name: '',
  })

  const fetchAll = () => {
    setLoading(true)
    Promise.all([projectApi.detail(projectId), documentApi.list(projectId)])
      .then(([p, d]) => {
        setProject(p.data)
        setDocs(d.data)
      })
      .catch(() => {})
      .finally(() => setLoading(false))
  }

  useEffect(() => {
    if (projectId) {
      projectApi.enter(projectId).catch(() => {})
    }
    fetchAll()
  }, [projectId])

  const handleUpload = async (file: File, docType: string) => {
    const lowerName = file.name.toLowerCase()
    const ext = lowerName.slice(lowerName.lastIndexOf('.'))
    if (ext === '.doc') {
      message.error('不支持旧版 .doc 格式，请用 Word 另存为 .docx 后再上传')
      return
    }
    if (!ACCEPTED_EXTENSIONS.includes(ext)) {
      message.error('仅支持 PDF、DOCX、TXT 格式')
      return
    }
    if (file.size > RESUMABLE_UPLOAD_LIMIT) {
      message.error('单个招标资料最大支持 1GB，请拆分后上传')
      return
    }

    let resumable = false
    setUploading(true)
    try {
      if (file.size <= NORMAL_UPLOAD_LIMIT) {
        await documentApi.upload(projectId, file, docType)
      } else {
        resumable = true
        const fingerprint = `fastvideo-upload:${projectId}:${docType}:${file.name}:${file.size}:${file.lastModified}`
        let uploadId = localStorage.getItem(fingerprint)
        let upload = null
        if (uploadId) {
          try {
            const resumed = await documentApi.resumableUploadStatus(projectId, uploadId)
            upload = resumed.data.status === 'uploading' ? resumed.data : null
          } catch {
            localStorage.removeItem(fingerprint)
          }
        }
        if (!upload) {
          const created = await documentApi.createResumableUpload(projectId, {
            file_name: file.name,
            file_size: file.size,
            doc_type: docType,
          })
          upload = created.data
          localStorage.setItem(fingerprint, upload.id)
        }

        const uploaded = new Set(upload.uploaded_chunks)
        for (let index = 0; index < upload.total_chunks; index += 1) {
          if (uploaded.has(index)) continue
          const start = index * upload.chunk_size
          const chunk = file.slice(start, Math.min(start + upload.chunk_size, file.size))
          const checksum = await sha256Hex(chunk)
          const result = await documentApi.uploadChunk(projectId, upload.id, index, chunk, checksum)
          upload = result.data
          setUploadProgress(upload.progress)
        }
        await documentApi.completeResumableUpload(projectId, upload.id)
        localStorage.removeItem(fingerprint)
      }
      message.success('上传成功，正在自动解析…')
      setTimeout(fetchAll, 1500)
    } catch (err: any) {
      // 业务错误（重复文件、类型不符、413、未登录等）已由 axios 拦截器统一提示；
      // 这里只在大文件分片传输中断时额外提示可续传。
      if (resumable && !err?.response) {
        message.info('上传中断，进度已保留；重新选择同一个文件可从已完成分片继续。')
      }
    } finally {
      setUploading(false)
      setUploadProgress(null)
    }
  }

  const handleReparse = async (docId: string) => {
    try {
      await documentApi.reparse(projectId, docId)
      message.success('已重新解析')
      setTimeout(fetchAll, 1500)
    } catch {
      // 拦截器已提示
    }
  }

  const handleDeleteDoc = async (docId: string) => {
    try {
      await documentApi.remove(projectId, docId)
      message.success('已删除')
      fetchAll()
    } catch {
      // 拦截器已提示
    }
  }

  const startEditingSummary = () => {
    if (!project) return
    setSummaryDraft({
      bid_area: project.bid_area ?? null,
      bid_deadline: project.bid_deadline ? dayjs(project.bid_deadline).format('YYYY-MM-DD') : '',
      construction_period: project.construction_period || '',
      bidder_name: project.bidder_name || '',
    })
    setEditingSummary(true)
  }

  const cancelEditingSummary = () => {
    setEditingSummary(false)
  }

  const saveSummary = async () => {
    setSavingSummary(true)
    const payload = {
      bid_area: summaryDraft.bid_area,
      bid_deadline: summaryDraft.bid_deadline || null,
      construction_period: summaryDraft.construction_period.trim() || null,
      bidder_name: summaryDraft.bidder_name.trim() || null,
    }
    try {
      await projectApi.update(projectId, payload)
      setProject((current) => current ? {
        ...current,
        bid_area: summaryDraft.bid_area ?? undefined,
        bid_deadline: summaryDraft.bid_deadline || undefined,
        construction_period: summaryDraft.construction_period.trim() || undefined,
        bidder_name: summaryDraft.bidder_name.trim() || undefined,
      } : current)
      setEditingSummary(false)
      message.success('项目关键参数已保存')
    } catch {
      // 拦截器已提示
    } finally {
      setSavingSummary(false)
    }
  }

  if (!project) {
    return <Card loading={loading}>加载中…</Card>
  }

  return (
    <div>
      <div className="page-header project-detail-header">
        <div className="page-heading">
          <div className="project-detail-title-row">
            <Title level={4} style={{ marginBottom: 4 }}>
              {project.name}
            </Title>
            {project.status === 'active' ? <Tag color="green">进行中</Tag> : <Tag>草稿</Tag>}
          </div>
          <Text type="secondary" className="page-description">
            {project.code ? `招标编号：${project.code} · ` : ''}创建于 {dayjs(project.created_at).format('YYYY-MM-DD')}
          </Text>
        </div>
      </div>

      <div className="project-summary-heading">
        <strong>项目关键参数</strong>
        {editingSummary ? (
          <Space>
            <Button icon={<CloseOutlined />} onClick={cancelEditingSummary} disabled={savingSummary}>取消</Button>
            <Button type="primary" icon={<CheckOutlined />} onClick={saveSummary} loading={savingSummary}>保存参数</Button>
          </Space>
        ) : (
          <Button icon={<EditOutlined />} onClick={startEditingSummary}>编辑参数</Button>
        )}
      </div>

      <Row className="project-summary-row" gutter={16} style={{ marginBottom: 16 }}>
        <Col xs={12} sm={12} lg={6}>
          <Card className={`project-summary-card${editingSummary ? ' is-editing' : ''}`}>
            {editingSummary ? (
              <label className="project-summary-edit-field">
                <span>建筑面积</span>
                <InputNumber
                  aria-label="建筑面积"
                  min={0}
                  value={summaryDraft.bid_area}
                  placeholder="请输入面积"
                  addonAfter="㎡"
                  onChange={(value) => setSummaryDraft((current) => ({ ...current, bid_area: value }))}
                />
              </label>
            ) : (
              <Statistic title="建筑面积" value={project.bid_area ? `${project.bid_area.toLocaleString()} ㎡` : '待识别'} />
            )}
          </Card>
        </Col>
        <Col xs={12} sm={12} lg={6}>
          <Card className={`project-summary-card${editingSummary ? ' is-editing' : ''}`}>
            {editingSummary ? (
              <label className="project-summary-edit-field">
                <span>投标截止</span>
                <DatePicker
                  aria-label="投标截止"
                  value={summaryDraft.bid_deadline ? dayjs(summaryDraft.bid_deadline) : null}
                  placeholder="选择日期"
                  format="YYYY-MM-DD"
                  allowClear
                  onChange={(value) => setSummaryDraft((current) => ({
                    ...current,
                    bid_deadline: value ? value.format('YYYY-MM-DD') : '',
                  }))}
                />
              </label>
            ) : (
              <Statistic title="投标截止" value={project.bid_deadline ? dayjs(project.bid_deadline).format('YYYY-MM-DD') : '待识别'} />
            )}
          </Card>
        </Col>
        <Col xs={12} sm={12} lg={6}>
          <Card className={`project-summary-card${editingSummary ? ' is-editing' : ''}`}>
            {editingSummary ? (
              <label className="project-summary-edit-field">
                <span>工期</span>
                <Input
                  aria-label="工期"
                  value={summaryDraft.construction_period}
                  placeholder="例如：730日历天"
                  onChange={(event) => setSummaryDraft((current) => ({ ...current, construction_period: event.target.value }))}
                />
              </label>
            ) : (
              <Statistic title="工期" value={project.construction_period || '待识别'} />
            )}
          </Card>
        </Col>
        <Col xs={12} sm={12} lg={6}>
          <Card className={`project-summary-card${editingSummary ? ' is-editing' : ''}`}>
            {editingSummary ? (
              <label className="project-summary-edit-field">
                <span>招标人</span>
                <Input
                  aria-label="招标人"
                  value={summaryDraft.bidder_name}
                  placeholder="请输入招标人"
                  onChange={(event) => setSummaryDraft((current) => ({ ...current, bidder_name: event.target.value }))}
                />
              </label>
            ) : (
              <Statistic title="招标人" value={project.bidder_name || '待识别'} />
            )}
          </Card>
        </Col>
      </Row>

      <Row gutter={16}>
        <Col span={24}>
          <Card
            className="project-documents-panel"
            title="招标资料"
            extra={
              <Space className="project-upload-actions" wrap>
                <Upload
                  accept=".pdf,.docx,.txt"
                  showUploadList={false}
                  beforeUpload={(file) => {
                    handleUpload(file, 'tender')
                    return false
                  }}
                >
                  <Button className="project-upload-button" icon={<UploadOutlined />} loading={uploading}>招标文件</Button>
                </Upload>
                <Upload
                  accept=".pdf,.docx,.txt"
                  showUploadList={false}
                  beforeUpload={(file) => {
                    handleUpload(file, 'construction')
                    return false
                  }}
                >
                  <Button className="project-upload-button" icon={<UploadOutlined />} loading={uploading}>施工资料</Button>
                </Upload>
                <Upload
                  accept=".pdf,.docx,.txt"
                  showUploadList={false}
                  beforeUpload={(file) => {
                    handleUpload(file, 'scoring')
                    return false
                  }}
                >
                  <Button className="project-upload-button" icon={<UploadOutlined />} loading={uploading}>评分办法</Button>
                </Upload>
              </Space>
            }
          >
            <div className="project-documents-intro">
              <div>
                <strong>资料中心</strong>
                <span>支持 PDF、DOCX、TXT。上传后会自动解析关键参数并保留来源页码。</span>
              </div>
              <span className="project-upload-limit">单文件最大 1GB</span>
            </div>
            {uploadProgress !== null && (
              <Progress
                className="project-upload-progress"
                percent={uploadProgress}
                status="active"
                format={(percent) => `大文件上传 ${percent}%（可中断续传）`}
                style={{ marginBottom: 16 }}
              />
            )}
            <Table<SourceDocument>
              rowKey="id"
              className="project-documents-table"
              size="small"
              loading={loading}
              dataSource={docs}
              pagination={false}
              tableLayout="fixed"
              locale={{ emptyText: '暂无资料，请从上方选择资料类型上传' }}
              columns={[
                {
                  title: '文件名',
                  dataIndex: 'file_name',
                  width: 250,
                  render: (v) => (
                    <div className="project-doc-name-cell">
                      <FileTextOutlined />
                      <Text ellipsis={{ tooltip: v }}>{v}</Text>
                    </div>
                  ),
                },
                {
                  title: '资料类型',
                  dataIndex: 'doc_type',
                  width: 105,
                  render: (v) => <span className="project-doc-type">{DOC_TYPE_LABEL[v] || v}</span>,
                },
                { title: '页数', dataIndex: 'page_count', width: 68, render: (v) => v ?? '待识别' },
                {
                  title: '解析状态',
                  dataIndex: 'parse_status',
                  width: 112,
                  render: (s) => {
                    const map: Record<string, { color: string; label: string }> = {
                      pending: { color: 'blue', label: '排队中' },
                      parsing: { color: 'processing', label: '解析中' },
                      success: { color: 'success', label: '解析成功' },
                      failed: { color: 'error', label: '解析失败' },
                    }
                    const item = map[s] || { color: 'default', label: s }
                    return <Tag color={item.color}>{item.label}</Tag>
                  },
                },
                {
                  title: '关键参数',
                  dataIndex: 'extracted_params',
                  width: 230,
                  render: (v) => {
                    if (!v || Object.keys(v).length === 0) return <span className="project-doc-param-empty">待提取</span>
                    const keys = Object.keys(v)
                    return (
                      <div className="project-doc-params">
                        <Tag color="blue">{keys.length} 项</Tag>
                        <Text
                          className="project-doc-param-summary"
                          ellipsis={{ tooltip: keys.slice(0, 3).map((k) => `${k}: ${v[k]?.value ?? ''}`).join('、') }}
                        >
                          {keys.slice(0, 2).map((k) => `${k}: ${v[k]?.value ?? ''}`).join('、')}
                          {keys.length > 2 ? ' 等' : ''}
                        </Text>
                      </div>
                    )
                  },
                },
                {
                  title: '操作',
                  width: 132,
                  render: (_, r) => (
                    <Space>
                      <Button size="small" icon={<ReloadOutlined />} onClick={() => handleReparse(r.id)}>
                        重新解析
                      </Button>
                      <Popconfirm title="删除该资料？" onConfirm={() => handleDeleteDoc(r.id)}>
                        <Button size="small" danger icon={<DeleteOutlined />} />
                      </Popconfirm>
                    </Space>
                  ),
                },
              ]}
            />
          </Card>
        </Col>
      </Row>

      <Row gutter={16} style={{ marginTop: 16 }}>
        <Col span={24}>
          <Card
            className="project-next-steps-panel"
            title="快速开始"
          >
            <div className="project-next-steps">
              <div className="project-next-steps-copy">
                <div className="project-flow-intro">
                  <div>
                    <strong>从资料到成片</strong>
                    <Text type="secondary">按照下面的顺序完成项目制作，每一步都有对应的操作入口。</Text>
                  </div>
                  <Tag color="blue">5 个步骤</Tag>
                </div>
                <ol className="project-flow-list">
                  {PROJECT_FLOW_STEPS.map((step, index) => (
                    <li className="project-flow-step" key={step.title}>
                      <span className="project-flow-index">{String(index + 1).padStart(2, '0')}</span>
                      <div className="project-flow-step-body">
                        <strong>{step.title}</strong>
                        <Text type="secondary">{step.description}</Text>
                      </div>
                    </li>
                  ))}
                </ol>
              </div>
              <Space className="project-next-steps-actions" wrap>
                <Button
                  type="primary"
                  icon={<PlayCircleOutlined />}
                  onClick={() => navigate(`/project/${projectId}/storyboard`)}
                >
                  生成解说词与分镜
                </Button>
                <Button icon={<BookOutlined />} onClick={() => navigate(`/project/${projectId}/reader`)}>
                  文档阅读器
                </Button>
                <Button icon={<DatabaseOutlined />} onClick={() => navigate(`/project/${projectId}/facts`)}>
                  参数台账
                </Button>
                <Button icon={<BgColorsOutlined />} onClick={() => navigate(`/project/${projectId}/render`)}>
                  画面制作
                </Button>
                <Button
                  icon={<VideoCameraOutlined />}
                  onClick={() => navigate(`/project/${projectId}/video`)}
                >
                  创建视频工程
                </Button>
              </Space>
            </div>
          </Card>
        </Col>
      </Row>
    </div>
  )
}
