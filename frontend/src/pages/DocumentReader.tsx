import { useEffect, useMemo, useState } from 'react'
import {
  Card,
  Typography,
  Space,
  Button,
  Input,
  List,
  Tag,
  Empty,
  Segmented,
  Divider,
  Spin,
  Descriptions,
  Select,
  Badge,
} from 'antd'
import {
  FileTextOutlined,
  SearchOutlined,
  ReloadOutlined,
  BookOutlined,
  ScanOutlined,
  TableOutlined,
} from '@ant-design/icons'
import { useParams } from 'react-router-dom'
import { documentApi, factApi, readerApi } from '../api'
import type { DocumentPage, SourceDocument, TocItem } from '../api/types'

const { Title, Text } = Typography

export default function DocumentReader() {
  const { projectId = '' } = useParams()
  const [docs, setDocs] = useState<SourceDocument[]>([])
  const [selectedDoc, setSelectedDoc] = useState<string>('')
  const [toc, setToc] = useState<TocItem[]>([])
  const [pages, setPages] = useState<DocumentPage[]>([])
  const [currentPage, setCurrentPage] = useState<number | null>(null)
  const [searchQ, setSearchQ] = useState('')
  const [searchResults, setSearchResults] = useState<any[]>([])
  const [loading, setLoading] = useState(false)
  const [pageLoading, setPageLoading] = useState(false)
  const [facts, setFacts] = useState<any[]>([])
  const [referencingShots, setReferencingShots] = useState<any[]>([])
  const [viewMode, setViewMode] = useState('阅读')
  const [ocrPages, setOcrPages] = useState(0)

  useEffect(() => {
    documentApi.list(projectId).then((res) => {
      setDocs(res.data)
      if (res.data.length > 0 && !selectedDoc) {
        setSelectedDoc(res.data[0].id)
      }
    })
  }, [projectId])

  useEffect(() => {
    if (!selectedDoc) return
    setLoading(true)
    setToc([])
    setPages([])
    setCurrentPage(null)
    Promise.all([
      documentApi.toc(projectId, selectedDoc),
      readerApi.pages(projectId, selectedDoc),
      readerApi.pageSummary(projectId, selectedDoc),
      factApi.list(projectId),
      readerApi.referencingShots(projectId, selectedDoc),
    ])
      .then(([tocRes, pagesRes, summary, factsRes, shotsRes]) => {
        setToc(tocRes.data)
        setPages(pagesRes.data)
        setOcrPages((summary.data.ocr_success || 0))
        setFacts(factsRes.data)
        setReferencingShots(shotsRes.data)
        if (pagesRes.data.length > 0) {
          setCurrentPage(pagesRes.data[0].page_number)
        }
      })
      .finally(() => setLoading(false))
  }, [selectedDoc, projectId])

  const currentPageData = useMemo(
    () => pages.find((p) => p.page_number === currentPage) || null,
    [pages, currentPage],
  )

  const pageFacts = useMemo(
    () => facts.filter((f) => f.document_id === selectedDoc && f.page_number === currentPage),
    [facts, selectedDoc, currentPage],
  )

  const handleSearch = () => {
    if (!searchQ.trim()) {
      setSearchResults([])
      return
    }
    documentApi.search(projectId, searchQ).then((res) => {
      setSearchResults(res.data)
    })
  }

  const handleGoToPage = (pageNumber: number | null | undefined) => {
    if (pageNumber) setCurrentPage(pageNumber)
  }

  const handleReparse = async () => {
    if (!selectedDoc) return
    await documentApi.reparse(projectId, selectedDoc)
    // 轮询解析状态
    const poll = setInterval(() => {
      documentApi.list(projectId).then((res) => {
        const doc = res.data.find((d) => d.id === selectedDoc)
        if (doc && ['success', 'failed'].includes(doc.parse_status)) {
          clearInterval(poll)
          // 重新加载
          readerApi.pages(projectId, selectedDoc).then((r) => setPages(r.data))
          readerApi.pageSummary(projectId, selectedDoc).then((s) => setOcrPages(s.data.ocr_success || 0))
        }
      })
    }, 1500)
  }

  const renderContent = () => {
    if (viewMode === '阅读') {
      if (!currentPageData) return <Empty description="选择左侧文档和页面" />
      const isScan = currentPageData.page_type === 'scan'
      const isOcr = currentPageData.extraction_method === 'ocr'
      return (
        <div>
          <Space style={{ marginBottom: 12 }}>
            <Tag color={isScan ? 'orange' : 'green'}>
              {isScan ? '扫描页' : currentPageData.page_type === 'mixed' ? '图文混合' : '文本页'}
            </Tag>
            <Tag color={isOcr ? 'purple' : 'blue'}>
              {isOcr ? 'OCR识别' : '原生文本'}
            </Tag>
            <Text type="secondary">{currentPageData.location_label}</Text>
            {currentPageData.ocr_status === 'failed' && (
              <Tag color="error">OCR失败</Tag>
            )}
          </Space>
          <pre
            className="reader-page-text"
            style={{
              whiteSpace: 'pre-wrap',
              wordBreak: 'break-word',
              background: '#F8FAFC',
              padding: 16,
              borderRadius: 8,
              maxHeight: 560,
              overflowY: 'auto',
              fontFamily: 'inherit',
              fontSize: 14,
              lineHeight: 1.8,
            }}
          >
            {currentPageData.cleaned_text || currentPageData.raw_text || '（本页无文本内容）'}
          </pre>
        </div>
      )
    }
    if (viewMode === '目录') {
      return (
        <List
          size="small"
          dataSource={toc}
          renderItem={(item, idx) => (
            <List.Item
              onClick={() => handleGoToPage(item.page || item.page_start)}
              style={{ paddingLeft: (item.level - 1) * 16, cursor: 'pointer' }}
            >
              <Space>
                <span style={{ fontWeight: item.level <= 1 ? 600 : 400 }}>
                  {item.heading_text}
                </span>
                <Text type="secondary" style={{ fontSize: 12 }}>
                  P{item.page || item.page_start}
                </Text>
              </Space>
            </List.Item>
          )}
          locale={{ emptyText: '未识别到目录结构' }}
        />
      )
    }
    if (viewMode === '搜索') {
      return (
        <div>
          <Input.Search
            placeholder="搜索文档内容…"
            value={searchQ}
            onChange={(e) => setSearchQ(e.target.value)}
            onSearch={handleSearch}
            allowClear
            style={{ marginBottom: 12 }}
          />
          <List
            size="small"
            dataSource={searchResults}
            renderItem={(r) => (
              <List.Item
                onClick={() => {
                  setSelectedDoc(r.document_id)
                  handleGoToPage(r.page)
                  setViewMode('阅读')
                }}
                style={{ cursor: 'pointer' }}
              >
                <Space direction="vertical" size={0} style={{ width: '100%' }}>
                  <Space>
                    <Text strong>{r.document_name}</Text>
                    {r.page && <Tag>P{r.page}</Tag>}
                  </Space>
                  <Text type="secondary" style={{ fontSize: 12 }} ellipsis>
                    {r.highlight}
                  </Text>
                </Space>
              </List.Item>
            )}
            locale={{ emptyText: '输入关键词搜索' }}
          />
        </div>
      )
    }
    return null
  }

  return (
    <div>
      <div className="page-header">
        <Title level={4} style={{ marginBottom: 4 }}>
          文档阅读器
        </Title>
        <Text type="secondary">
          按页阅读招标资料，查看原文、表格、OCR 标记与提取参数
        </Text>
      </div>

      <Card className="reader-shell" styles={{ body: { padding: 0 } }}>
        <div className="reader-layout">
          {/* 左侧：文档列表 + 目录 */}
          <div className="reader-sidebar">
            <Text strong>文档列表</Text>
            <Select
              style={{ width: '100%', marginTop: 8 }}
              value={selectedDoc}
              onChange={setSelectedDoc}
              options={docs.map((d) => ({
                value: d.id,
                label: `${d.file_name}（${d.total_pages || 0}页）`,
              }))}
            />
            {selectedDoc && (
              <Button
                size="small"
                icon={<ReloadOutlined />}
                style={{ marginTop: 8, width: '100%' }}
                onClick={handleReparse}
              >
                重新解析
              </Button>
            )}
            <Divider style={{ margin: '12px 0' }} />
            <Text strong>页面导航</Text>
            <div className="reader-page-list">
              <List
                size="small"
                dataSource={pages}
                renderItem={(p) => (
                  <List.Item
                    onClick={() => setCurrentPage(p.page_number)}
                    className={`reader-page-item ${currentPage === p.page_number ? 'is-selected' : ''}`}
                  >
                    <Space>
                      <Badge
                        status={
                          p.page_type === 'scan'
                            ? p.ocr_status === 'success'
                              ? 'processing'
                              : p.ocr_status === 'failed'
                                ? 'error'
                                : 'warning'
                            : 'success'
                        }
                      />
                      <Text style={{ fontSize: 12 }}>P{p.page_number}</Text>
                      {p.page_type === 'scan' && <ScanOutlined style={{ fontSize: 12, color: '#fa8c16' }} />}
                      {p.page_type === 'mixed' && <TableOutlined style={{ fontSize: 12, color: '#2457A6' }} />}
                    </Space>
                  </List.Item>
                )}
              />
            </div>
          </div>

          {/* 中间：正文 */}
          <div className="reader-main">
            <Segmented
              value={viewMode}
              onChange={(v) => setViewMode(String(v))}
              options={[
                { label: '阅读', value: '阅读', icon: <BookOutlined /> },
                { label: '目录', value: '目录', icon: <FileTextOutlined /> },
                { label: '搜索', value: '搜索', icon: <SearchOutlined /> },
              ]}
              style={{ marginBottom: 12 }}
            />
            {loading || pageLoading ? (
              <Spin style={{ display: 'block', margin: '40px auto' }} />
            ) : (
              renderContent()
            )}
          </div>

          {/* 右侧：当前页参数 + 评分点 + 引用分镜 */}
          <div className="reader-inspector">
            <Text strong>本页提取参数</Text>
            {pageFacts.length === 0 && (
              <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="本页无参数" />
            )}
            {pageFacts.map((f) => (
              <Card key={f.id} size="small" style={{ marginBottom: 8 }}>
                <Space direction="vertical" size={0} style={{ width: '100%' }}>
                  <Space>
                    <Text strong style={{ fontSize: 12 }}>{f.fact_label || f.fact_name || '待识别数字'}</Text>
                    {f.verification_status === 'conflict' && <Tag color="error">冲突</Tag>}
                    {f.verification_status === 'confirmed' && <Tag color="success">已确认</Tag>}
                    {f.verification_status === 'unverified' && f.usage_status === 'auto_usable' && (
                      <Tag color="processing">AI可用</Tag>
                    )}
                    {f.verification_status === 'unverified' && f.usage_status === 'review' && (
                      <Tag color="warning">待审核</Tag>
                    )}
                    {f.verification_status === 'unverified' && f.usage_status === 'low_confidence' && (
                      <Tag>自动排除</Tag>
                    )}
                  </Space>
                  <Text>{f.fact_value}{f.unit}</Text>
                  {f.source_quote && (
                    <Text type="secondary" style={{ fontSize: 11 }} ellipsis={{ tooltip: f.source_quote }}>
                      「{f.source_quote}」
                    </Text>
                  )}
                </Space>
              </Card>
            ))}

            <Divider style={{ margin: '12px 0' }} />
            <Text strong>引用本页/本文件的分镜</Text>
            {referencingShots.length === 0 && (
              <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无引用" />
            )}
            {referencingShots.map((s) => (
              <Card key={s.id} size="small" style={{ marginBottom: 8 }}>
                <Space direction="vertical" size={0}>
                  <Text strong style={{ fontSize: 12 }}>
                    #{s.sequence} {s.title}
                  </Text>
                  <Text type="secondary" style={{ fontSize: 11 }} ellipsis>
                    {s.narration}
                  </Text>
                </Space>
              </Card>
            ))}

            <Divider style={{ margin: '12px 0' }} />
            <Space>
              <Text type="secondary">OCR成功页：</Text>
              <Tag color="purple">{ocrPages}</Tag>
            </Space>
          </div>
        </div>
      </Card>
    </div>
  )
}
