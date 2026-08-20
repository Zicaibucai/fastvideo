import { useEffect, useState } from 'react'
import {
  Card,
  Typography,
  Space,
  Table,
  Tag,
  Button,
  App,
  Segmented,
  Modal,
  Input,
  Tooltip,
  Empty,
  Descriptions,
  Alert,
} from 'antd'
import {
  CheckCircleOutlined,
  CloseCircleOutlined,
  WarningOutlined,
  EditOutlined,
  LinkOutlined,
} from '@ant-design/icons'
import { useParams, useNavigate } from 'react-router-dom'
import { factApi } from '../api'
import type { ExtractedFact } from '../api/types'

const { Title, Text } = Typography

const STATUS_LABEL: Record<string, { label: string; color: string }> = {
  unverified: { label: '待确认', color: 'default' },
  confirmed: { label: '已确认', color: 'success' },
  rejected: { label: '已驳回', color: 'error' },
  conflict: { label: '冲突', color: 'warning' },
}

export default function Facts() {
  const { projectId = '' } = useParams()
  const navigate = useNavigate()
  const { message } = App.useApp()
  const [facts, setFacts] = useState<ExtractedFact[]>([])
  const [filter, setFilter] = useState('all')
  const [loading, setLoading] = useState(false)
  const [confirmModal, setConfirmModal] = useState<ExtractedFact | null>(null)
  const [confirmValue, setConfirmValue] = useState('')
  const [confirmUnit, setConfirmUnit] = useState('')

  const fetchFacts = () => {
    setLoading(true)
    const params: any = {}
    if (filter === 'unverified') params.unverified_only = true
    if (filter === 'conflict') params.status = 'conflict'
    if (filter === 'confirmed') params.status = 'confirmed'
    factApi
      .list(projectId, params)
      .then((res) => setFacts(res.data))
      .finally(() => setLoading(false))
  }

  useEffect(fetchFacts, [projectId, filter])

  const handleConfirm = async (fact: ExtractedFact) => {
    try {
      await factApi.confirm(projectId, fact.id, {
        status: 'confirmed',
        fact_value: confirmValue || fact.fact_value,
        unit: confirmUnit || fact.unit || undefined,
      })
      message.success('已确认该参数')
      setConfirmModal(null)
      fetchFacts()
    } catch {
      // 拦截器已提示
    }
  }

  const handleReject = async (fact: ExtractedFact) => {
    try {
      await factApi.confirm(projectId, fact.id, { status: 'rejected' })
      message.success('已驳回该参数')
      fetchFacts()
    } catch {
      // 拦截器已提示
    }
  }

  const openConfirm = (fact: ExtractedFact) => {
    setConfirmModal(fact)
    setConfirmValue(fact.fact_value)
    setConfirmUnit(fact.unit || '')
  }

  const openSource = (fact: ExtractedFact) => {
    if (fact.document_id && fact.page_number) {
      navigate(`/project/${projectId}/reader`, {
        state: { docId: fact.document_id, page: fact.page_number },
      })
    } else {
      message.info('该参数无来源文件')
    }
  }

  const conflictCount = facts.filter((f) => f.verification_status === 'conflict').length
  const unverifiedCount = facts.filter((f) => f.verification_status === 'unverified').length
  const confirmedCount = facts.filter((f) => f.verification_status === 'confirmed').length

  const columns = [
    {
      title: '参数',
      dataIndex: 'fact_name',
      width: 140,
      render: (v: string) => <b>{v}</b>,
    },
    {
      title: '数值',
      dataIndex: 'fact_value',
      width: 120,
      render: (v: string, r: ExtractedFact) => `${v}${r.unit || ''}`,
    },
    {
      title: '来源',
      width: 220,
      render: (_: unknown, r: ExtractedFact) => (
        <Space direction="vertical" size={0}>
          <Text style={{ fontSize: 12 }}>{r.document_name || '未知文档'}</Text>
          {r.page_number && (
            <Button
              type="link"
              size="small"
              style={{ padding: 0, fontSize: 12 }}
              icon={<LinkOutlined />}
              onClick={() => openSource(r)}
            >
              P{r.page_number} · {r.location_label}
            </Button>
          )}
        </Space>
      ),
    },
    {
      title: '原文',
      dataIndex: 'source_quote',
      ellipsis: true,
      render: (v: string) =>
        v ? (
          <Tooltip title={v}>
            <Text type="secondary" style={{ fontSize: 12 }}>
              「{v.slice(0, 30)}…」
            </Text>
          </Tooltip>
        ) : (
          <Text type="secondary">—</Text>
        ),
    },
    {
      title: '置信度',
      dataIndex: 'confidence',
      width: 90,
      render: (v: number) => `${Math.round((v || 0) * 100)}%`,
    },
    {
      title: '状态',
      dataIndex: 'verification_status',
      width: 100,
      render: (s: string) => {
        const item = STATUS_LABEL[s] || { label: s, color: 'default' }
        return <Tag color={item.color}>{item.label}</Tag>
      },
    },
    {
      title: '操作',
      width: 180,
      render: (_: unknown, r: ExtractedFact) => (
        <Space>
          {r.verification_status !== 'confirmed' && (
            <Button
              size="small"
              type="primary"
              icon={<CheckCircleOutlined />}
              onClick={() => openConfirm(r)}
            >
              确认
            </Button>
          )}
          {r.verification_status !== 'rejected' && (
            <Button size="small" danger icon={<CloseCircleOutlined />} onClick={() => handleReject(r)}>
              驳回
            </Button>
          )}
          {r.verification_status === 'confirmed' && (
            <Button size="small" icon={<EditOutlined />} onClick={() => openConfirm(r)}>
              修改
            </Button>
          )}
        </Space>
      ),
    },
  ]

  return (
    <div>
      <div className="page-header" style={{ display: 'flex', justifyContent: 'space-between' }}>
        <div>
          <Title level={4} style={{ marginBottom: 4 }}>
            工程参数台账
          </Title>
          <Text type="secondary">
            从招标资料中提取的工程参数，带来源定位与人工确认
          </Text>
        </div>
        <Segmented
          value={filter}
          onChange={(v) => setFilter(String(v))}
          options={[
            { label: `全部(${facts.length})`, value: 'all' },
            { label: `待确认(${unverifiedCount})`, value: 'unverified' },
            { label: `冲突(${conflictCount})`, value: 'conflict' },
            { label: `已确认(${confirmedCount})`, value: 'confirmed' },
          ]}
        />
      </div>

      {conflictCount > 0 && (
        <Alert
          type="warning"
          showIcon
          icon={<WarningOutlined />}
          style={{ marginBottom: 16 }}
          message={`发现 ${conflictCount} 条参数存在来源冲突`}
          description="同一参数在不同文件中数值不一致，已标记为冲突。冲突数据不会进入正式解说词，请人工确认最终采用值。"
        />
      )}

      <Card>
        {facts.length === 0 ? (
          <Empty description="暂无参数，请先上传并解析招标资料" />
        ) : (
          <Table<ExtractedFact>
            rowKey="id"
            loading={loading}
            dataSource={facts}
            columns={columns}
            pagination={{ pageSize: 20, showSizeChanger: false }}
            expandable={{
              expandedRowRender: (r) =>
                r.verification_status === 'conflict' && r.candidates ? (
                  <div>
                    <Text strong>冲突来源对比：</Text>
                    <Table
                      size="small"
                      pagination={false}
                      dataSource={r.candidates}
                      rowKey={(c) => c.id || c.document_id + c.page_number}
                      columns={[
                        {
                          title: '来源文件',
                          dataIndex: 'document_id',
                          render: () => (
                            <Text style={{ fontSize: 12 }}>
                              {facts.find((f) => f.id === r.candidates?.[0]?.id)?.document_name || '未知'}
                            </Text>
                          ),
                        },
                        { title: '页码', dataIndex: 'page_number', width: 80 },
                        { title: '数值', dataIndex: 'fact_value', width: 120 },
                        {
                          title: '原文',
                          dataIndex: 'source_quote',
                          ellipsis: true,
                          render: (v: string) => <Text style={{ fontSize: 12 }}>「{v}」</Text>,
                        },
                      ]}
                    />
                  </div>
                ) : null,
            }}
          />
        )}
      </Card>

      <Modal
        title={`确认参数 - ${confirmModal?.fact_name || ''}`}
        open={!!confirmModal}
        onOk={() => confirmModal && handleConfirm(confirmModal)}
        onCancel={() => setConfirmModal(null)}
        okText="确认采用"
      >
        <Descriptions column={1} size="small">
          <Descriptions.Item label="当前值">
            {confirmModal?.fact_value}
            {confirmModal?.unit}
          </Descriptions.Item>
          <Descriptions.Item label="来源">
            {confirmModal?.document_name} P{confirmModal?.page_number}
          </Descriptions.Item>
          <Descriptions.Item label="原文">
            {confirmModal?.source_quote}
          </Descriptions.Item>
        </Descriptions>
        <div style={{ marginTop: 16 }}>
          <Text>确认数值：</Text>
          <Input
            value={confirmValue}
            onChange={(e) => setConfirmValue(e.target.value)}
            style={{ marginTop: 8 }}
          />
        </div>
        <div style={{ marginTop: 8 }}>
          <Text>单位：</Text>
          <Input
            value={confirmUnit}
            onChange={(e) => setConfirmUnit(e.target.value)}
            style={{ marginTop: 8 }}
            placeholder="可选，如 ㎡、日历天"
          />
        </div>
      </Modal>
    </div>
  )
}
