import { useEffect, useState } from 'react'
import {
  Card,
  Table,
  Button,
  Space,
  Modal,
  Form,
  Input,
  Tag,
  Typography,
  App,
  Popconfirm,
} from 'antd'
import { PlusOutlined, EditOutlined, DeleteOutlined, ArrowRightOutlined } from '@ant-design/icons'
import { useNavigate } from 'react-router-dom'
import { projectApi } from '../api'
import type { Project } from '../api/types'
import dayjs from 'dayjs'

const { Title, Text } = Typography

export default function Projects() {
  const navigate = useNavigate()
  const { message } = App.useApp()
  const [items, setItems] = useState<Project[]>([])
  const [loading, setLoading] = useState(false)
  const [modalOpen, setModalOpen] = useState(false)
  const [form] = Form.useForm()
  const [saving, setSaving] = useState(false)

  const fetchList = () => {
    setLoading(true)
    projectApi
      .list({ page_size: 100 })
      .then((res) => setItems(res.data.items))
      .finally(() => setLoading(false))
  }

  useEffect(fetchList, [])

  const handleCreate = () => {
    form.resetFields()
    setModalOpen(true)
  }

  const handleSubmit = async () => {
    const values = await form.validateFields()
    setSaving(true)
    try {
      await projectApi.create(values)
      message.success('项目创建成功')
      setModalOpen(false)
      fetchList()
    } catch {
      // 拦截器已提示
    } finally {
      setSaving(false)
    }
  }

  const handleDelete = async (id: string) => {
    try {
      await projectApi.remove(id)
      message.success('已删除')
      fetchList()
    } catch {
      // 拦截器已提示
    }
  }

  return (
    <div>
      <div className="page-header" style={{ display: 'flex', justifyContent: 'space-between' }}>
        <div>
          <Title level={4} style={{ marginBottom: 4 }}>
            投标项目
          </Title>
          <Text type="secondary">管理招标项目及其全部视频生产流程</Text>
        </div>
        <Button type="primary" icon={<PlusOutlined />} onClick={handleCreate}>
          新建项目
        </Button>
      </div>

      <Card>
        <Table<Project>
          rowKey="id"
          loading={loading}
          dataSource={items}
          columns={[
            {
              title: '项目名称',
              dataIndex: 'name',
              render: (v, r) => (
                <Space direction="vertical" size={0}>
                  <b>{v}</b>
                  {r.code && <Text type="secondary" style={{ fontSize: 12 }}>招标编号：{r.code}</Text>}
                </Space>
              ),
            },
            {
              title: '建筑面积',
              dataIndex: 'bid_area',
              width: 140,
              render: (v, r) =>
                v ? (
                  <span>
                    {v.toLocaleString()} ㎡
                    {r.area_source_page && (
                      <Text type="secondary" style={{ fontSize: 12 }}>（P{r.area_source_page}）</Text>
                    )}
                  </span>
                ) : (
                  <Text type="secondary">—</Text>
                ),
            },
            {
              title: '工期',
              dataIndex: 'construction_period',
              width: 140,
              render: (v) => v || <Text type="secondary">—</Text>,
            },
            {
              title: '状态',
              dataIndex: 'status',
              width: 100,
              render: (s) => (s === 'active' ? <Tag color="green">进行中</Tag> : <Tag>草稿</Tag>),
            },
            { title: '资料', dataIndex: 'doc_count', width: 70 },
            { title: '分镜', dataIndex: 'shot_count', width: 70 },
            { title: '素材', dataIndex: 'asset_count', width: 70 },
            {
              title: '创建时间',
              dataIndex: 'created_at',
              width: 120,
              render: (v) => dayjs(v).format('YYYY-MM-DD'),
            },
            {
              title: '操作',
              width: 200,
              render: (_, r) => (
                <Space>
                  <Button
                    size="small"
                    type="primary"
                    icon={<ArrowRightOutlined />}
                    onClick={() => navigate(`/project/${r.id}`)}
                  >
                    进入
                  </Button>
                  <Button
                    size="small"
                    icon={<EditOutlined />}
                    onClick={() => navigate(`/project/${r.id}`)}
                  />
                  <Popconfirm title="确认删除该项目？" onConfirm={() => handleDelete(r.id)}>
                    <Button size="small" danger icon={<DeleteOutlined />} />
                  </Popconfirm>
                </Space>
              ),
            },
          ]}
        />
      </Card>

      <Modal
        title="新建投标项目"
        open={modalOpen}
        onOk={handleSubmit}
        onCancel={() => setModalOpen(false)}
        confirmLoading={saving}
      >
        <Form form={form} layout="vertical">
          <Form.Item name="name" label="项目名称" rules={[{ required: true, message: '请输入项目名称' }]}>
            <Input placeholder="例如：XX市市民中心建设工程" />
          </Form.Item>
          <Form.Item name="code" label="招标编号">
            <Input placeholder="例如：ZB-2026-001" />
          </Form.Item>
          <Form.Item name="description" label="项目简介">
            <Input.TextArea rows={3} placeholder="可选" />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  )
}
