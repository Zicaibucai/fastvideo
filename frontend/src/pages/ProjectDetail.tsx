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
  Alert,
  Popconfirm,
  Progress,
  Upload,
} from 'antd'
import {
  UploadOutlined,
  FileTextOutlined,
  ReloadOutlined,
  DeleteOutlined,
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
import { TaskTag } from '../components/TaskStatus'

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

const NORMAL_UPLOAD_LIMIT = 100 * 1024 * 1024
const RESUMABLE_UPLOAD_LIMIT = 1024 * 1024 * 1024

export default function ProjectDetail() {
  const { projectId = '' } = useParams()
  const navigate = useNavigate()
  const { message } = App.useApp()
  const [project, setProject] = useState<Project | null>(null)
  const [docs, setDocs] = useState<SourceDocument[]>([])
  const [loading, setLoading] = useState(false)
  const [uploading, setUploading] = useState(false)
  const [uploadProgress, setUploadProgress] = useState<number | null>(null)

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

  useEffect(fetchAll, [projectId])

  const handleUpload = async (file: File, docType: string) => {
    if (file.size > RESUMABLE_UPLOAD_LIMIT) {
      message.error('单个招标资料最大支持 1GB，请拆分后上传')
      return
    }
    setUploading(true)
    try {
      if (file.size <= NORMAL_UPLOAD_LIMIT) {
        await documentApi.upload(projectId, file, docType)
      } else {
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
          const result = await documentApi.uploadChunk(projectId, upload.id, index, chunk)
          upload = result.data
          setUploadProgress(upload.progress)
        }
        await documentApi.completeResumableUpload(projectId, upload.id)
        localStorage.removeItem(fingerprint)
      }
      message.success('上传成功，正在自动解析…')
      setTimeout(fetchAll, 1500)
    } catch {
      message.info('大文件上传已保留进度；重新选择同一个文件可从已完成分片继续。')
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

  if (!project) {
    return <Card loading={loading}>加载中…</Card>
  }

  return (
    <div>
      <div className="page-header">
        <Title level={4} style={{ marginBottom: 4 }}>
          {project.name}
          {project.status === 'active' ? <Tag color="green" style={{ marginLeft: 8 }}>进行中</Tag> : <Tag style={{ marginLeft: 8 }}>草稿</Tag>}
        </Title>
        <Text type="secondary">
          {project.code ? `招标编号：${project.code} · ` : ''}创建于 {dayjs(project.created_at).format('YYYY-MM-DD')}
        </Text>
      </div>

      <Row gutter={16} style={{ marginBottom: 16 }}>
        <Col span={6}>
          <Card><Statistic title="建筑面积" value={project.bid_area ? `${project.bid_area.toLocaleString()} ㎡` : '—'} /></Card>
        </Col>
        <Col span={6}>
          <Card><Statistic title="投标截止" value={project.bid_deadline ? dayjs(project.bid_deadline).format('YYYY-MM-DD') : '—'} /></Card>
        </Col>
        <Col span={6}>
          <Card><Statistic title="工期" value={project.construction_period || '—'} /></Card>
        </Col>
        <Col span={6}>
          <Card><Statistic title="招标人" value={project.bidder_name || '—'} /></Card>
        </Col>
      </Row>

      {project.area_source_page && (
        <Alert type="info" showIcon style={{ marginBottom: 16 }}
          message={`关键参数已从招标文件提取并标注来源页码（如建筑面积来源于 P${project.area_source_page}），确保 AI 生成内容有据可查。`}
        />
      )}

      <Row gutter={16}>
        <Col span={24}>
          <Card
            title="招标资料"
            extra={
              <Space>
                <Upload
                  accept=".pdf,.docx,.doc,.txt"
                  showUploadList={false}
                  beforeUpload={(file) => {
                    handleUpload(file, 'tender')
                    return false
                  }}
                >
                  <Button icon={<UploadOutlined />} loading={uploading}>上传招标文件</Button>
                </Upload>
                <Upload
                  accept=".pdf,.docx,.doc,.txt"
                  showUploadList={false}
                  beforeUpload={(file) => {
                    handleUpload(file, 'construction')
                    return false
                  }}
                >
                  <Button icon={<UploadOutlined />} loading={uploading}>上传施组/资料</Button>
                </Upload>
                <Upload
                  accept=".pdf,.docx,.doc,.txt"
                  showUploadList={false}
                  beforeUpload={(file) => {
                    handleUpload(file, 'scoring')
                    return false
                  }}
                >
                  <Button icon={<UploadOutlined />} loading={uploading}>上传评分办法</Button>
                </Upload>
              </Space>
            }
          >
            {uploadProgress !== null && (
              <Progress
                percent={uploadProgress}
                status="active"
                format={(percent) => `大文件上传 ${percent}%（可中断续传）`}
                style={{ marginBottom: 16 }}
              />
            )}
            <Table<SourceDocument>
              rowKey="id"
              size="small"
              loading={loading}
              dataSource={docs}
              pagination={false}
              columns={[
                {
                  title: '文件名',
                  dataIndex: 'file_name',
                  render: (v) => (
                    <Space>
                      <FileTextOutlined />
                      {v}
                    </Space>
                  ),
                },
                { title: '类型', dataIndex: 'doc_type', width: 120, render: (v) => DOC_TYPE_LABEL[v] || v },
                { title: '页数', dataIndex: 'page_count', width: 80, render: (v) => v ?? '—' },
                {
                  title: '解析状态',
                  dataIndex: 'parse_status',
                  width: 140,
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
                  render: (v) => {
                    if (!v || Object.keys(v).length === 0) return <Text type="secondary">—</Text>
                    const keys = Object.keys(v)
                    return (
                      <Space wrap size={4}>
                        {keys.map((k) => (
                          <Tag key={k} color="geekblue">
                            {k}: {v[k].value}（P{v[k].page}）
                          </Tag>
                        ))}
                      </Space>
                    )
                  },
                },
                {
                  title: '操作',
                  width: 180,
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
            title="快速开始"
            extra={
              <Space>
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
            }
          >
            <Text type="secondary">
              上传招标资料后，系统将自动解析关键参数（面积、工期、日期等，并记录来源页码）。
              随后可进入「解说词与分镜」由 AI 自动生成分镜文案，生成画面与配音，最终合成投标视频。
            </Text>
          </Card>
        </Col>
      </Row>
    </div>
  )
}
