import { useCallback, useEffect, useState } from 'react'
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
  Select,
} from 'antd'
import { PlusOutlined, EditOutlined, DeleteOutlined, ArrowRightOutlined } from '@ant-design/icons'
import { useNavigate } from 'react-router-dom'
import { projectApi } from '../api'
import type { Project } from '../api/types'
import dayjs from 'dayjs'

const { Title, Text } = Typography

type ProjectSortBy = 'last_entered_at' | 'created_at' | 'name'

export default function Projects() {
  const navigate = useNavigate()
  const { message } = App.useApp()
  const [items, setItems] = useState<Project[]>([])
  const [loading, setLoading] = useState(false)
  const [modalOpen, setModalOpen] = useState(false)
  const [form] = Form.useForm()
  const [saving, setSaving] = useState(false)
  const [sortBy, setSortBy] = useState<ProjectSortBy>('last_entered_at')

  const fetchList = useCallback(() => {
    setLoading(true)
    projectApi
      .list({
        page_size: 100,
        sort_by: sortBy,
        sort_order: sortBy === 'name' ? 'asc' : 'desc',
      })
      .then((res) => setItems(res.data.items))
      .finally(() => setLoading(false))
  }, [sortBy])

  useEffect(() => {
    fetchList()
  }, [fetchList])

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
      <div className="page-header">
        <div>
          <Title level={4} style={{ marginBottom: 4 }}>
            投标项目
          </Title>
        </div>
        <Space wrap>
          <Space size={8}>
            <Text type="secondary">排序方式</Text>
            <Select<ProjectSortBy>
              aria-label="项目排序方式"
              value={sortBy}
              onChange={setSortBy}
              options={[
                { value: 'last_entered_at', label: '最近进入' },
                { value: 'created_at', label: '最新创建' },
                { value: 'name', label: '项目名称' },
              ]}
              style={{ width: 122 }}
            />
          </Space>
          <Button type="primary" icon={<PlusOutlined />} onClick={handleCreate}>
            新建项目
          </Button>
        </Space>
      </div>

      <Card>
        <Table<Project>
          rowKey="id"
          className="projects-table"
          tableLayout="fixed"
          loading={loading}
          dataSource={items}
          columns={[
            {
              title: '项目名称',
              dataIndex: 'name',
              width: 210,
              render: (v, r) => (
                <Space className="project-name-cell" direction="vertical" size={0}>
                  <b>{v}</b>
                  {r.code && <Text type="secondary" style={{ fontSize: 12 }}>招标编号：{r.code}</Text>}
                </Space>
              ),
            },
            {
              title: '状态',
              dataIndex: 'status',
              width: 75,
              render: (s) => (s === 'active' ? <Tag color="green">进行中</Tag> : <Tag>草稿</Tag>),
            },
            {
              title: '最后进入',
              dataIndex: 'last_entered_at',
              width: 140,
              render: (v) => (v ? dayjs(v).format('YYYY-MM-DD HH:mm') : <Text type="secondary">未进入</Text>),
            },
            { title: '资料', dataIndex: 'doc_count', width: 65 },
            { title: '分镜', dataIndex: 'shot_count', width: 65 },
            { title: '素材', dataIndex: 'asset_count', width: 65 },
            {
              title: '创建时间',
              dataIndex: 'created_at',
              width: 120,
              render: (v) => dayjs(v).format('YYYY-MM-DD'),
            },
            {
              title: '操作',
              width: 185,
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
