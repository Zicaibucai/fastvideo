import { useEffect, useState } from 'react'
import { Card, Row, Col, Statistic, Table, Button, Space, Typography, Tag, Progress } from 'antd'
import {
  FolderOutlined,
  FileTextOutlined,
  VideoCameraOutlined,
  PictureOutlined,
  PlusOutlined,
  ArrowRightOutlined,
} from '@ant-design/icons'
import { useNavigate } from 'react-router-dom'
import { projectApi, taskApi } from '../api'
import type { Project, RenderTask } from '../api/types'
import { TaskTag, taskTypeLabel } from '../components/TaskStatus'

const { Title, Text } = Typography

export default function Home() {
  const navigate = useNavigate()
  const [projects, setProjects] = useState<Project[]>([])
  const [tasks, setTasks] = useState<RenderTask[]>([])
  const [loading, setLoading] = useState(false)

  useEffect(() => {
    setLoading(true)
    Promise.all([projectApi.list({ page_size: 5 }), taskApi.list({})])
      .then(([p, t]) => {
        setProjects(p.data.items)
        setTasks(t.data)
      })
      .finally(() => setLoading(false))
  }, [])

  const totals = {
    projects: projects.length,
    docs: projects.reduce((s, p) => s + (p.doc_count || 0), 0),
    shots: projects.reduce((s, p) => s + (p.shot_count || 0), 0),
    assets: projects.reduce((s, p) => s + (p.asset_count || 0), 0),
  }

  const activeTaskCount = tasks.filter((t) => ['queued', 'running', 'retry'].includes(t.status)).length
  const failedTaskCount = tasks.filter((t) => t.status === 'failed').length

  return (
    <div>
      <div className="page-header">
        <Title level={4} style={{ marginBottom: 4 }}>
          项目总览
        </Title>
        <Text type="secondary">欢迎使用建筑工程AI投标视频平台</Text>
      </div>

      <Row gutter={16}>
        <Col span={6}>
          <Card>
            <Statistic title="投标项目" value={totals.projects} prefix={<FolderOutlined />} />
          </Card>
        </Col>
        <Col span={6}>
          <Card>
            <Statistic title="招标资料" value={totals.docs} prefix={<FileTextOutlined />} />
          </Card>
        </Col>
        <Col span={6}>
          <Card>
            <Statistic title="解说词分镜" value={totals.shots} prefix={<VideoCameraOutlined />} />
          </Card>
        </Col>
        <Col span={6}>
          <Card>
            <Statistic title="素材文件" value={totals.assets} prefix={<PictureOutlined />} />
          </Card>
        </Col>
      </Row>

      <Row gutter={16} style={{ marginTop: 16 }}>
        <Col span={16}>
          <Card
            title="最近项目"
            extra={
              <Button type="primary" icon={<PlusOutlined />} onClick={() => navigate('/projects')}>
                新建项目
              </Button>
            }
          >
            <Table<Project>
              rowKey="id"
              size="small"
              loading={loading}
              pagination={false}
              dataSource={projects}
              columns={[
                { title: '项目名称', dataIndex: 'name', render: (v) => <b>{v}</b> },
                {
                  title: '状态',
                  dataIndex: 'status',
                  width: 100,
                  render: (s) =>
                    s === 'active' ? <Tag color="green">进行中</Tag> : <Tag>草稿</Tag>,
                },
                { title: '资料', dataIndex: 'doc_count', width: 80 },
                { title: '分镜', dataIndex: 'shot_count', width: 80 },
                { title: '素材', dataIndex: 'asset_count', width: 80 },
                {
                  title: '操作',
                  width: 140,
                  render: (_, r) => (
                    <Space>
                      <Button size="small" type="link" onClick={() => navigate(`/project/${r.id}`)}>
                        进入 <ArrowRightOutlined />
                      </Button>
                    </Space>
                  ),
                },
              ]}
            />
          </Card>
        </Col>
        <Col span={8}>
          <Card title="AI 任务动态">
            <Space direction="vertical" style={{ width: '100%' }}>
              <Row gutter={8}>
                <Col span={12}>
                  <Card size="small">
                    <Statistic title="进行中" value={activeTaskCount} valueStyle={{ color: '#1d4ed8' }} />
                  </Card>
                </Col>
                <Col span={12}>
                  <Card size="small">
                    <Statistic title="失败待重试" value={failedTaskCount} valueStyle={{ color: '#cf1322' }} />
                  </Card>
                </Col>
              </Row>
              <Card size="small" title="最近任务" styles={{ body: { paddingTop: 8 } }}>
                {tasks.length === 0 && <Text type="secondary">暂无任务</Text>}
                {tasks.slice(0, 5).map((t) => (
                  <div key={t.id} style={{ display: 'flex', justifyContent: 'space-between', padding: '4px 0' }}>
                    <Text>{taskTypeLabel(t.task_type)}</Text>
                    <TaskTag status={t.status} />
                  </div>
                ))}
              </Card>
            </Space>
          </Card>
        </Col>
      </Row>
    </div>
  )
}
