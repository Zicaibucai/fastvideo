import { useEffect, useMemo, useState } from 'react'
import {
  Alert,
  App,
  Button,
  Card,
  Descriptions,
  Empty,
  Input,
  Modal,
  Select,
  Segmented,
  Space,
  Table,
  Tag,
  Typography,
} from 'antd'
import {
  CheckCircleOutlined,
  CloseCircleOutlined,
  EditOutlined,
  LinkOutlined,
} from '@ant-design/icons'
import { useNavigate, useParams } from 'react-router-dom'
import { factApi } from '../api'
import type { ExtractedFact } from '../api/types'

const { Paragraph, Text, Title } = Typography

const STATUS_LABEL: Record<string, { label: string; color: string }> = {
  unverified: { label: '未确认', color: 'default' },
  confirmed: { label: '已确认', color: 'success' },
  rejected: { label: '已忽略', color: 'error' },
  conflict: { label: '来源冲突', color: 'warning' },
}

const USAGE_LABEL: Record<string, { label: string; color: string }> = {
  confirmed: { label: '已确认使用', color: 'success' },
  auto_usable: { label: '高置信度，可供 AI 使用', color: 'processing' },
  review: { label: '待审核', color: 'warning' },
  low_confidence: { label: '低于60%，自动排除', color: 'default' },
  conflict: { label: '待处理冲突', color: 'warning' },
  rejected: { label: '已忽略，不使用', color: 'default' },
}

function usageFor(fact: ExtractedFact) {
  return USAGE_LABEL[fact.usage_status || 'review'] || USAGE_LABEL.review
}

function uniqueOptions(values: Array<string | undefined>) {
  return Array.from(new Set(values.filter(Boolean) as string[]))
    .sort((a, b) => a.localeCompare(b, 'zh-CN', { numeric: true }))
    .map((value) => ({ label: value, value }))
}

export default function Facts() {
  const { projectId = '' } = useParams()
  const navigate = useNavigate()
  const { message } = App.useApp()
  const [allFacts, setAllFacts] = useState<ExtractedFact[]>([])
  const [filter, setFilter] = useState('all')
  const [search, setSearch] = useState('')
  const [nameFilter, setNameFilter] = useState<string>()
  const [scopeFilter, setScopeFilter] = useState<string>()
  const [categoryFilter, setCategoryFilter] = useState<string>()
  const [unitFilter, setUnitFilter] = useState<string>()
  const [documentFilter, setDocumentFilter] = useState<string>()
  const [usageFilter, setUsageFilter] = useState<string>()
  const [sortBy, setSortBy] = useState('default')
  const [sortOrder, setSortOrder] = useState<'ascend' | 'descend'>('ascend')
  const [loading, setLoading] = useState(false)
  const [confirmModal, setConfirmModal] = useState<ExtractedFact | null>(null)
  const [confirmValue, setConfirmValue] = useState('')
  const [confirmUnit, setConfirmUnit] = useState('')

  const fetchFacts = () => {
    setLoading(true)
    factApi
      .list(projectId)
      .then((res) => setAllFacts(res.data))
      .finally(() => setLoading(false))
  }

  useEffect(() => {
    fetchFacts()
  }, [projectId])

  const filterOptions = useMemo(() => ({
    names: uniqueOptions(allFacts.map((fact) => fact.fact_label || '待识别数字')),
    scopes: uniqueOptions(allFacts.map((fact) => fact.scope)),
    categories: uniqueOptions(allFacts.map((fact) => fact.category)),
    units: uniqueOptions(allFacts.map((fact) => fact.unit)),
    documents: uniqueOptions(allFacts.map((fact) => fact.document_name)),
  }), [allFacts])

  const facts = useMemo(() => {
    let filtered: ExtractedFact[]
    if (filter === 'unverified') {
      filtered = allFacts.filter(
        (fact) => fact.verification_status === 'unverified' && fact.usage_status === 'review',
      )
    } else if (filter === 'conflict') {
      filtered = allFacts.filter((fact) => fact.verification_status === 'conflict')
    } else if (filter === 'confirmed') {
      filtered = allFacts.filter((fact) => fact.verification_status === 'confirmed')
    } else {
      filtered = allFacts
    }
    filtered = filtered.filter((fact) => (
      (!nameFilter || (fact.fact_label || '待识别数字') === nameFilter)
      && (!scopeFilter || fact.scope === scopeFilter)
      && (!categoryFilter || fact.category === categoryFilter)
      && (!unitFilter || fact.unit === unitFilter)
      && (!documentFilter || fact.document_name === documentFilter)
      && (!usageFilter || (fact.usage_status || 'review') === usageFilter)
    ))
    const query = search.trim().toLowerCase()
    if (query) {
      filtered = filtered.filter((fact) =>
        [fact.fact_label, fact.fact_value, fact.unit, fact.scope, fact.category, fact.source_quote, fact.document_name]
          .filter(Boolean)
          .some((value) => String(value).toLowerCase().includes(query)),
      )
    }
    if (sortBy === 'default') return filtered

    const compareText = (left: string | undefined, right: string | undefined) =>
      (left || '').localeCompare(right || '', 'zh-CN', { numeric: true, sensitivity: 'base' })
    const compareSource = (left: ExtractedFact, right: ExtractedFact) => (
      compareText(left.document_name, right.document_name)
      || ((left.source_order ?? Number.MAX_SAFE_INTEGER) - (right.source_order ?? Number.MAX_SAFE_INTEGER))
      || ((left.page_number ?? Number.MAX_SAFE_INTEGER) - (right.page_number ?? Number.MAX_SAFE_INTEGER))
      || compareText(left.location_label, right.location_label)
      || compareText(left.created_at, right.created_at)
    )
    const compare = (left: ExtractedFact, right: ExtractedFact) => {
      if (sortBy === 'source') return compareSource(left, right)
      if (sortBy === 'confidence') return (left.confidence || 0) - (right.confidence || 0)
      if (sortBy === 'name') return compareText(left.fact_label, right.fact_label)
      if (sortBy === 'value') return compareText(left.fact_value, right.fact_value)
      if (sortBy === 'usage') return compareText(usageFor(left).label, usageFor(right).label)
      return 0
    }
    return [...filtered].sort((left, right) => {
      const result = compare(left, right)
      return sortOrder === 'ascend' ? result : -result
    })
  }, [
    allFacts,
    filter,
    search,
    nameFilter,
    scopeFilter,
    categoryFilter,
    unitFilter,
    documentFilter,
    usageFilter,
    sortBy,
    sortOrder,
  ])

  const resetFilters = () => {
    setSearch('')
    setFilter('all')
    setNameFilter(undefined)
    setScopeFilter(undefined)
    setCategoryFilter(undefined)
    setUnitFilter(undefined)
    setDocumentFilter(undefined)
    setUsageFilter(undefined)
    setSortBy('default')
    setSortOrder('ascend')
  }

  const handleConfirm = async (fact: ExtractedFact) => {
    try {
      await factApi.confirm(projectId, fact.id, {
        status: 'confirmed',
        fact_value: confirmValue || fact.fact_value,
        unit: confirmUnit || fact.unit || undefined,
      })
      message.success('已确认，该信息可作为正式事实使用')
      setConfirmModal(null)
      fetchFacts()
    } catch {
      // 拦截器已提示
    }
  }

  const handleReject = async (fact: ExtractedFact) => {
    try {
      await factApi.confirm(projectId, fact.id, { status: 'rejected' })
      message.success('已忽略，该信息仍保留在历史记录中')
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
      message.info('该信息没有可定位的来源')
    }
  }

  const conflictCount = allFacts.filter((fact) => fact.verification_status === 'conflict').length
  const unverifiedCount = allFacts.filter(
    (fact) => fact.verification_status === 'unverified' && fact.usage_status === 'review',
  ).length
  const confirmedCount = allFacts.filter((fact) => fact.verification_status === 'confirmed').length

  const columns = [
    {
      title: '工程信息',
      width: 190,
      render: (_: unknown, fact: ExtractedFact) => (
        <div>
          <Text strong className="facts-name">{fact.fact_label || '待识别数字'}</Text>
          {fact.scope && <Text className="facts-scope">适用对象：{fact.scope}</Text>}
          {fact.category && <Text className="facts-category">类别：{fact.category}</Text>}
        </div>
      ),
    },
    {
      title: '数值',
      width: 160,
      render: (_: unknown, fact: ExtractedFact) => (
        <Text className="facts-value">{fact.fact_value}{fact.unit || ''}</Text>
      ),
    },
    {
      title: '原文依据',
      width: 520,
      render: (_: unknown, fact: ExtractedFact) => (
        <div className="facts-evidence">
          {fact.source_quote ? (
            <Paragraph
              className="facts-quote"
              ellipsis={{ rows: 1, expandable: true, symbol: '展开全文' }}
            >
              「{fact.source_quote}」
            </Paragraph>
          ) : (
            <Text type="secondary">没有保存原文依据</Text>
          )}
          <Space size={6} className="facts-source-line">
            <Text type="secondary">{fact.document_name || '未知文件'}</Text>
            {fact.page_number && (
              <Button
                type="link"
                size="small"
                icon={<LinkOutlined />}
                onClick={() => openSource(fact)}
              >
                第{fact.page_number}页{fact.location_label ? `，${fact.location_label}` : ''}
              </Button>
            )}
          </Space>
        </div>
      ),
    },
    {
      title: '置信度与用途',
      width: 180,
      render: (_: unknown, fact: ExtractedFact) => {
        const usage = usageFor(fact)
        return (
          <Space direction="vertical" size={4}>
            <Text>{Math.round((fact.confidence || 0) * 100)}%</Text>
            <Tag color={usage.color}>{usage.label}</Tag>
          </Space>
        )
      },
    },
    {
      title: '核对状态',
      width: 120,
      render: (_: unknown, fact: ExtractedFact) => {
        const status = STATUS_LABEL[fact.verification_status] || STATUS_LABEL.unverified
        return <Tag color={status.color}>{status.label}</Tag>
      },
    },
    {
      title: '操作',
      width: 180,
      render: (_: unknown, fact: ExtractedFact) => (
        <Space>
          {fact.verification_status !== 'confirmed' && (
            <Button
              size="small"
              type="primary"
              icon={<CheckCircleOutlined />}
              onClick={() => openConfirm(fact)}
            >
              确认
            </Button>
          )}
          {fact.verification_status !== 'rejected' && (
            <Button size="small" danger icon={<CloseCircleOutlined />} onClick={() => handleReject(fact)}>
              忽略
            </Button>
          )}
          {fact.verification_status === 'confirmed' && (
            <Button size="small" icon={<EditOutlined />} onClick={() => openConfirm(fact)}>
              修改
            </Button>
          )}
        </Space>
      ),
    },
  ]

  return (
    <div className="facts-page">
      <div className="page-header facts-page-header">
        <div>
          <Title level={4} style={{ marginBottom: 4 }}>工程信息核对</Title>
          <Text type="secondary">
            系统从资料中保留数字、型号和尺寸，并结合原文上下文整理参数。适用对象表示参数属于主楼、地下室等哪一部分；参数类别只是面积、尺寸、材料/设备等筛选标签，不改变原文数值。80%以上自动供 AI 使用，60%–80%进入待审核，低于60%保留但不审核、不写入解说词。
          </Text>
        </div>
      </div>

      <div className="facts-toolbar">
        <Text type="secondary">共保留 {allFacts.length} 条证据，当前显示 {facts.length} 条</Text>
        <Space wrap>
          <Input.Search
            allowClear
            value={search}
            onChange={(event) => setSearch(event.target.value)}
            placeholder="搜索参数、数值或原文"
            style={{ width: 240 }}
          />
          <Segmented
            value={filter}
            onChange={(value) => setFilter(String(value))}
            options={[
              { label: `全部 ${allFacts.length}`, value: 'all' },
              { label: `待审核 ${unverifiedCount}`, value: 'unverified' },
              { label: `冲突 ${conflictCount}`, value: 'conflict' },
              { label: `已确认 ${confirmedCount}`, value: 'confirmed' },
            ]}
          />
        </Space>
      </div>

      <div className="facts-filter-panel">
        <Space wrap size={[8, 8]}>
          <Select
            allowClear
            showSearch
            optionFilterProp="label"
            placeholder="参数名称"
            value={nameFilter}
            onChange={setNameFilter}
            options={filterOptions.names}
            className="facts-filter-select facts-filter-select-wide"
          />
          <Select
            allowClear
            showSearch
            optionFilterProp="label"
            placeholder="适用对象"
            value={scopeFilter}
            onChange={setScopeFilter}
            options={filterOptions.scopes}
            className="facts-filter-select"
          />
          <Select
            allowClear
            showSearch
            optionFilterProp="label"
            placeholder="参数类别"
            value={categoryFilter}
            onChange={setCategoryFilter}
            options={filterOptions.categories}
            className="facts-filter-select"
          />
          <Select
            allowClear
            showSearch
            optionFilterProp="label"
            placeholder="单位"
            value={unitFilter}
            onChange={setUnitFilter}
            options={filterOptions.units}
            className="facts-filter-select"
          />
          <Select
            allowClear
            showSearch
            optionFilterProp="label"
            placeholder="来源文件"
            value={documentFilter}
            onChange={setDocumentFilter}
            options={filterOptions.documents}
            className="facts-filter-select facts-filter-select-wide"
          />
          <Select
            allowClear
            placeholder="用途状态"
            value={usageFilter}
            onChange={setUsageFilter}
            options={Object.entries(USAGE_LABEL).map(([value, item]) => ({ label: item.label, value }))}
            className="facts-filter-select facts-filter-select-wide"
          />
          <Select
            value={sortBy}
            onChange={setSortBy}
            options={[
              { label: '默认排序', value: 'default' },
              { label: '按来源先后', value: 'source' },
              { label: '按置信度', value: 'confidence' },
              { label: '按参数名称', value: 'name' },
              { label: '按数值', value: 'value' },
              { label: '按用途状态', value: 'usage' },
            ]}
            className="facts-filter-select facts-filter-select-wide"
          />
          <Select
            value={sortOrder}
            onChange={setSortOrder}
            options={[
              { label: '升序', value: 'ascend' },
              { label: '降序', value: 'descend' },
            ]}
            className="facts-filter-select facts-filter-select-order"
          />
          <Button size="small" onClick={resetFilters}>清空筛选</Button>
        </Space>
      </div>

      <Card className="facts-card">
        {!loading && allFacts.length === 0 ? (
          <Empty description="暂无数字证据，请先上传并解析招标资料" />
        ) : (
          <Table<ExtractedFact>
            rowKey="id"
            loading={loading}
            dataSource={facts}
            columns={columns}
            scroll={{ x: 1350 }}
            size="small"
            pagination={{
              defaultPageSize: 100,
              pageSizeOptions: [50, 100, 200],
              showSizeChanger: true,
              showTotal: (total) => `共 ${total} 条`,
            }}
            expandable={{
              rowExpandable: (fact) => fact.verification_status === 'conflict' && Boolean(fact.candidates?.length),
              expandedRowRender: (fact) => (
                <div className="facts-conflict-detail">
                  <Text strong>来源对比</Text>
                  <Table
                    size="small"
                    pagination={false}
                    dataSource={fact.candidates || []}
                    rowKey={(candidate) => candidate.id || `${candidate.document_id}-${candidate.page_number}-${candidate.fact_value}`}
                    columns={[
                      { title: '来源文件', dataIndex: 'document_name', render: (value: string) => value || '未知文件' },
                      { title: '页码', dataIndex: 'page_number', width: 80 },
                      {
                        title: '范围',
                        dataIndex: 'scope',
                        width: 100,
                        render: (value: string) => value || '—',
                      },
                      {
                        title: '数值',
                        dataIndex: 'fact_value',
                        width: 120,
                        render: (value: string, candidate: any) => `${value || ''}${candidate.unit || ''}`,
                      },
                      {
                        title: '原文依据',
                        dataIndex: 'source_quote',
                        render: (value: string) => <Paragraph ellipsis={{ rows: 2, expandable: true }}>{value || '无'}</Paragraph>,
                      },
                    ]}
                  />
                </div>
              ),
            }}
          />
        )}
      </Card>

      <Modal
        title={`确认工程信息：${confirmModal?.fact_label || '待识别数字'}`}
        open={!!confirmModal}
        onOk={() => confirmModal && handleConfirm(confirmModal)}
        onCancel={() => setConfirmModal(null)}
        okText="确认采用"
        cancelText="取消"
      >
        <Alert
          type="info"
          showIcon
          style={{ marginBottom: 16 }}
          message="确认后会作为 AI 可引用的正式事实"
        />
        <Descriptions column={1} size="small">
          <Descriptions.Item label="当前值">{confirmModal?.fact_value}{confirmModal?.unit}</Descriptions.Item>
          <Descriptions.Item label="来源">{confirmModal?.document_name}，第{confirmModal?.page_number}页</Descriptions.Item>
          <Descriptions.Item label="完整原文">
            <Paragraph className="facts-modal-quote">{confirmModal?.source_quote || '无'}</Paragraph>
          </Descriptions.Item>
        </Descriptions>
        <div style={{ marginTop: 16 }}>
          <Text>确认数值</Text>
          <Input value={confirmValue} onChange={(event) => setConfirmValue(event.target.value)} style={{ marginTop: 8 }} />
        </div>
        <div style={{ marginTop: 8 }}>
          <Text>单位</Text>
          <Input
            value={confirmUnit}
            onChange={(event) => setConfirmUnit(event.target.value)}
            style={{ marginTop: 8 }}
            placeholder="例如 ㎡、mm、日历天"
          />
        </div>
      </Modal>
    </div>
  )
}
