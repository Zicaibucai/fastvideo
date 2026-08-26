import { useEffect, useState } from 'react'
import {
  Card,
  Typography,
  Button,
  Space,
  Table,
  Tag,
  App,
  Popconfirm,
  Upload,
  Segmented,
  Image,
  Tooltip,
  Descriptions,
  Input,
  Modal,
} from 'antd'
import {
  DownloadOutlined,
  EditOutlined,
  UploadOutlined,
  DeleteOutlined,
  PictureOutlined,
  PlayCircleOutlined,
  FileOutlined,
  SoundOutlined,
} from '@ant-design/icons'
import { useParams } from 'react-router-dom'
import { assetApi, downloadAssetFile } from '../api'
import { withAuthToken } from '../api/client'
import type { Asset } from '../api/types'

const { Title, Text } = Typography

const TYPE_LABEL: Record<string, string> = {
  image: '图片',
  video: '视频',
  audio: '音频',
  model: '模型',
  document: '文档',
}

const SOURCE_LABEL: Record<string, { label: string; color: string }> = {
  upload: { label: '上传', color: 'blue' },
  ai_image: { label: 'AI图片', color: 'purple' },
  ai_video: { label: 'AI视频', color: 'purple' },
  ai_tts: { label: 'AI配音', color: 'purple' },
  model_shot: { label: '模型截图', color: 'cyan' },
  render: { label: '渲染结果', color: 'green' },
  video_template_frame: { label: '模板关键帧', color: 'geekblue' },
}

const SOURCE_OPTIONS_BY_TYPE: Record<string, { label: string; value: string }[]> = {
  image: [
    { label: '全部来源', value: 'all' },
    { label: '上传', value: 'upload' },
    { label: 'AI生成', value: 'ai_image' },
    { label: '模型截图', value: 'model_shot' },
    { label: '模板关键帧', value: 'video_template_frame' },
    { label: '渲染结果', value: 'render' },
  ],
  video: [
    { label: '全部来源', value: 'all' },
    { label: '上传', value: 'upload' },
    { label: 'AI生成', value: 'ai_video' },
    { label: '视频工程合成', value: 'render' },
  ],
}

const sourceDisplay = (source: string, assetType: string) => {
  if (source === 'render' && assetType === 'video') return '视频工程合成'
  return SOURCE_LABEL[source]?.label || source
}

export default function Assets() {
  const { projectId = '' } = useParams()
  const { message } = App.useApp()
  const [items, setItems] = useState<Asset[]>([])
  const [loading, setLoading] = useState(false)
  const [typeFilter, setTypeFilter] = useState<string>('all')
  const [sourceFilter, setSourceFilter] = useState<string>('all')
  const [preview, setPreview] = useState<Asset | null>(null)
  const [renameOpen, setRenameOpen] = useState(false)
  const [renameTarget, setRenameTarget] = useState<Asset | null>(null)
  const [renameValue, setRenameValue] = useState('')
  const [renaming, setRenaming] = useState(false)

  const fetchAssets = () => {
    setLoading(true)
    const source = typeFilter === 'image' || typeFilter === 'video'
      ? (sourceFilter === 'all' ? undefined : sourceFilter)
      : undefined
    assetApi
      .list(
        projectId,
        typeFilter === 'all' ? undefined : typeFilter,
        source,
      )
      .then((res) => setItems(res.data))
      .finally(() => setLoading(false))
  }

  useEffect(fetchAssets, [projectId, typeFilter, sourceFilter])

  const handleUpload = async (file: File) => {
    try {
      await assetApi.upload(projectId, file, file.name)
      message.success('素材上传成功')
      fetchAssets()
    } catch {
      // 拦截器已提示
    }
    return false
  }

  const handleDelete = async (id: string) => {
    try {
      await assetApi.remove(projectId, id)
      message.success('已删除')
      fetchAssets()
    } catch {
      // 拦截器已提示
    }
  }

  const openRename = (asset: Asset) => {
    setRenameTarget(asset)
    setRenameValue(asset.name)
    setRenameOpen(true)
  }

  const handleRename = async () => {
    if (!renameTarget) return
    const name = renameValue.trim()
    if (!name) {
      message.warning('请输入素材名称')
      return
    }
    setRenaming(true)
    try {
      const res = await assetApi.update(projectId, renameTarget.id, { name })
      setItems((current) => current.map((item) => (item.id === res.data.id ? res.data : item)))
      setPreview((current) => (current?.id === res.data.id ? res.data : current))
      setRenameOpen(false)
      setRenameTarget(null)
      message.success('素材已重命名')
    } catch {
      // 拦截器已提示
    } finally {
      setRenaming(false)
    }
  }

  const handleDownload = async (asset: Asset) => {
    try {
      await downloadAssetFile(asset)
    } catch {
      message.error('素材下载失败')
    }
  }

  const fileUrl = (a: Asset) =>
    a.file_key ? withAuthToken(`/files/${a.file_key}`) : withAuthToken(a.url || '')

  return (
    <div>
      <div className="page-header">
        <div>
          <Title level={4} style={{ marginBottom: 4 }}>
            素材库
          </Title>
          <Text type="secondary">
            图片、视频、音频、模型截图等素材统一管理，支持 AI 生成素材复用
          </Text>
        </div>
        <Space className="page-actions" direction="vertical" align="end" style={{ width: 'min(100%, 760px)' }}>
          <Segmented
            block
            options={[
              { label: '全部', value: 'all' },
              { label: '图片', value: 'image' },
              { label: '视频', value: 'video' },
              { label: '音频', value: 'audio' },
              { label: '模型', value: 'model' },
              { label: '文档', value: 'document' },
            ]}
            value={typeFilter}
            onChange={(v) => {
              setTypeFilter(String(v))
              setSourceFilter('all')
            }}
          />
          <Space wrap style={{ width: '100%', justifyContent: 'flex-end' }}>
            {(typeFilter === 'image' || typeFilter === 'video') && (
              <Space size={8}>
                <Text type="secondary">来源</Text>
                <Segmented
                  options={SOURCE_OPTIONS_BY_TYPE[typeFilter]}
                  value={sourceFilter}
                  onChange={(v) => setSourceFilter(String(v))}
                />
              </Space>
            )}
            <Upload showUploadList={false} beforeUpload={handleUpload}>
              <Button type="primary" icon={<UploadOutlined />}>
                上传素材
              </Button>
            </Upload>
          </Space>
        </Space>
      </div>

      <Card>
        <Table<Asset>
          rowKey="id"
          loading={loading}
          dataSource={items}
          pagination={{ pageSize: 10, showSizeChanger: false }}
          columns={[
            {
              title: '预览',
              dataIndex: 'asset_type',
              width: 100,
              render: (_, r) => {
                const url = fileUrl(r)
                if (!url) return <FileOutlined style={{ fontSize: 24, color: '#999' }} />
                if (r.asset_type === 'image') {
                  return (
                    <Image src={url} width={72} height={48} style={{ objectFit: 'cover', borderRadius: 6 }} />
                  )
                }
                if (r.asset_type === 'audio') {
                  return (
                    <Button size="small" onClick={() => window.open(url)}>
                      <SoundOutlined /> 试听
                    </Button>
                  )
                }
                if (r.asset_type === 'video') {
                  return (
                    <Button size="small" onClick={() => window.open(url)}>
                      <PlayCircleOutlined /> 播放
                    </Button>
                  )
                }
                return <FileOutlined style={{ fontSize: 24, color: '#999' }} />
              },
            },
            { title: '名称', dataIndex: 'name', ellipsis: true },
            {
              title: '类型',
              dataIndex: 'asset_type',
              width: 90,
              render: (v) => <Tag>{TYPE_LABEL[v] || v}</Tag>,
            },
            {
              title: '来源',
              dataIndex: 'source',
              width: 100,
              render: (v, r) => {
                const item = SOURCE_LABEL[v] || { label: v, color: 'default' }
                return <Tag color={item.color}>{sourceDisplay(v, r.asset_type)}</Tag>
              },
            },
            {
              title: '分类/版本',
              width: 150,
              render: (_, r) => (
                <Space direction="vertical" size={0}>
                  <Text>{r.meta?.category || r.project_stage || '常规素材'}</Text>
                  {(r.tags || []).includes('视频模板试生成') && <Tag color="gold">模板试生成</Tag>}
                  {r.meta?.version && <Text type="secondary">V{r.meta.version}{r.meta.is_current ? ' · 当前' : ' · 历史'}</Text>}
                </Space>
              ),
            },
            {
              title: '尺寸/时长',
              width: 130,
              render: (_, r) => {
                if (r.width && r.height) return `${r.width}×${r.height}`
                if (r.duration_seconds) return `${r.duration_seconds}s`
                return `${(r.file_size / 1024).toFixed(0)} KB`
              },
            },
            {
              title: '操作',
              width: 210,
              render: (_, r) => (
                <Space>
                  <Tooltip title="查看详情">
                    <Button size="small" onClick={() => setPreview(r)}>
                      详情
                    </Button>
                  </Tooltip>
                  <Tooltip title="重命名">
                    <Button size="small" icon={<EditOutlined />} onClick={() => openRename(r)} />
                  </Tooltip>
                  <Tooltip title="下载">
                    <Button size="small" icon={<DownloadOutlined />} onClick={() => handleDownload(r)} />
                  </Tooltip>
                  <Popconfirm title="删除该素材？" onConfirm={() => handleDelete(r.id)}>
                    <Button size="small" danger icon={<DeleteOutlined />} />
                  </Popconfirm>
                </Space>
              ),
            },
          ]}
        />
      </Card>

      <Modal
        title={preview?.name}
        open={!!preview}
        onCancel={() => setPreview(null)}
        footer={null}
        width={520}
      >
        {preview && (
          <div>
            {preview.asset_type === 'image' && fileUrl(preview) && (
              <Image src={fileUrl(preview)!} style={{ width: '100%', borderRadius: 8 }} />
            )}
            {preview.asset_type === 'video' && fileUrl(preview) && (
              <video controls style={{ width: '100%', borderRadius: 8 }} src={fileUrl(preview)!} />
            )}
            {preview.asset_type === 'audio' && fileUrl(preview) && (
              <audio controls style={{ width: '100%' }} src={fileUrl(preview)!} />
            )}
            <Descriptions column={1} size="small" style={{ marginTop: 12 }}>
              <Descriptions.Item label="类型">{TYPE_LABEL[preview.asset_type]}</Descriptions.Item>
              <Descriptions.Item label="来源">{sourceDisplay(preview.source, preview.asset_type)}</Descriptions.Item>
              <Descriptions.Item label="文件大小">{(preview.file_size / 1024).toFixed(0)} KB</Descriptions.Item>
              {preview.width && preview.height && (
                <Descriptions.Item label="尺寸">
                  {preview.width}×{preview.height}
                </Descriptions.Item>
              )}
              {preview.duration_seconds && (
                <Descriptions.Item label="时长">{preview.duration_seconds}s</Descriptions.Item>
              )}
              {preview.prompt && (
                <Descriptions.Item label="生成提示词">{preview.prompt}</Descriptions.Item>
              )}
              {preview.meta?.category && (
                <Descriptions.Item label="素材分类">{preview.meta.category}</Descriptions.Item>
              )}
              {preview.tags?.length ? (
                <Descriptions.Item label="标签">{preview.tags.join('、')}</Descriptions.Item>
              ) : null}
              {preview.meta?.version && (
                <Descriptions.Item label="版本">V{preview.meta.version}{preview.meta.is_current ? '（当前）' : '（历史）'}</Descriptions.Item>
              )}
            </Descriptions>
          </div>
        )}
      </Modal>

      <Modal
        title="重命名素材"
        open={renameOpen}
        onCancel={() => setRenameOpen(false)}
        onOk={handleRename}
        okText="保存"
        confirmLoading={renaming}
      >
        <Input
          autoFocus
          value={renameValue}
          maxLength={255}
          showCount
          placeholder="请输入素材名称"
          onChange={(e) => setRenameValue(e.target.value)}
          onPressEnter={handleRename}
        />
      </Modal>
    </div>
  )
}
