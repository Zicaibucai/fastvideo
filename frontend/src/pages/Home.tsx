import { useEffect, useMemo, useState } from 'react'
import {
  AppstoreOutlined,
  ArrowRightOutlined,
  ClockCircleOutlined,
  DollarOutlined,
  FileTextOutlined,
  FolderOutlined,
  SettingOutlined,
  PictureOutlined,
  ReloadOutlined,
  ThunderboltOutlined,
  VideoCameraOutlined,
} from '@ant-design/icons'
import { App, Button, Card, InputNumber, Modal, Skeleton, Space, Tag, Typography } from 'antd'
import { useNavigate } from 'react-router-dom'
import { projectApi, renderApi, taskApi, videoGenApi } from '../api'
import type { Project, RenderJobTask, RenderTask, VideoGenerationJob } from '../api/types'
import { TaskTag, taskTypeLabel } from '../components/TaskStatus'
import {
  getProjectActiveDays,
  getProjectActivityDays,
  getRecentlyOpenedProjects,
} from '../recentProjects'

const { Title, Text } = Typography

// 费率先集中在前端，后续接入统一计费配置接口时只需替换这里。
// 页面会把所有结果标为“估算”，避免演示费率被误认为实际账单。
const DEFAULT_BILLING_RATES = {
  seedancePerSecond: 0.32,
  textPerThousandTokens: 0.02,
}

const BILLING_RATES_KEY = 'fastvideo_billing_rates'

type BillingRates = typeof DEFAULT_BILLING_RATES

type ProjectTelemetry = {
  projectId: string
  videoJobs: VideoGenerationJob[]
  renderJobs: RenderJobTask[]
}

type TrendPoint = {
  key: string
  label: string
  value: number
}

function dateKey(date: Date): string {
  const year = date.getFullYear()
  const month = String(date.getMonth() + 1).padStart(2, '0')
  const day = String(date.getDate()).padStart(2, '0')
  return `${year}-${month}-${day}`
}

function valueDateKey(value?: unknown): string {
  if (!value) return ''
  const date = new Date(String(value))
  return Number.isNaN(date.getTime()) ? '' : dateKey(date)
}

function numberFrom(value: unknown): number {
  return typeof value === 'number' && Number.isFinite(value) ? value : 0
}

function compactNumber(value: number): string {
  if (value >= 10000) return `${(value / 10000).toFixed(1)}万`
  return new Intl.NumberFormat('zh-CN', { maximumFractionDigits: 0 }).format(value)
}

function currency(value: number): string {
  return `¥${value.toFixed(2)}`
}

function projectVisitTime(value?: string): string {
  if (!value) return '尚未进入'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return '尚未进入'
  return new Intl.DateTimeFormat('zh-CN', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
  }).format(date)
}

function readUsageValue(source: unknown, keys: string[]): number {
  if (!source || typeof source !== 'object') return 0
  const record = source as Record<string, unknown>
  for (const key of keys) {
    const value = numberFrom(record[key])
    if (value > 0) return value
  }
  return 0
}

function taskTokenUsage(task: RenderTask): number {
  const result = task.result as Record<string, unknown> | undefined
  if (!result) return 0
  const usage = result.usage || result.token_usage || result
  const total = readUsageValue(usage, ['total_tokens', 'totalTokens', 'token_count', 'tokens'])
  if (total > 0) return total
  return readUsageValue(usage, ['input_tokens', 'prompt_tokens', 'inputTokens'])
    + readUsageValue(usage, ['output_tokens', 'completion_tokens', 'outputTokens'])
}

function explicitVideoCost(job: VideoGenerationJob): number {
  const snapshot = job.parameter_snapshot as Record<string, unknown> | undefined
  return readUsageValue(snapshot, ['actual_cost', 'estimated_cost', 'cost'])
}

function readBillingRates(): BillingRates {
  if (typeof window === 'undefined') return DEFAULT_BILLING_RATES
  try {
    const raw = window.localStorage.getItem(BILLING_RATES_KEY)
    const saved = raw ? JSON.parse(raw) : {}
    const readPositiveRate = (value: unknown, fallback: number) => (
      typeof value === 'number' && Number.isFinite(value) && value > 0 ? value : fallback
    )
    return {
      seedancePerSecond: readPositiveRate(
        saved.seedancePerSecond,
        DEFAULT_BILLING_RATES.seedancePerSecond,
      ),
      textPerThousandTokens: readPositiveRate(
        saved.textPerThousandTokens,
        DEFAULT_BILLING_RATES.textPerThousandTokens,
      ),
    }
  } catch {
    return DEFAULT_BILLING_RATES
  }
}

function videoJobCost(job: VideoGenerationJob, rates: BillingRates): number {
  const explicit = explicitVideoCost(job)
  if (explicit > 0) return explicit
  if (job.provider !== 'seedance' && !String(job.model_name || '').toLowerCase().includes('seedance')) {
    return 0
  }
  return Math.max(0, numberFrom(job.duration)) * rates.seedancePerSecond
}

function projectCost(telemetry: ProjectTelemetry | undefined, rates: BillingRates): number {
  if (!telemetry) return 0
  const videoCost = telemetry.videoJobs
    .filter((job) => job.status !== 'cancelled')
    .reduce((sum, job) => sum + videoJobCost(job, rates), 0)
  const renderCost = telemetry.renderJobs
    .filter((job) => job.status !== 'cancelled')
    .reduce((sum, job) => sum + numberFrom(job.actual_cost || job.estimated_cost), 0)
  return videoCost + renderCost
}

function projectActiveDays(project: Project): number {
  // 新版按自然日记录；旧项目没有历史记录时，用后端最后进入时间至少记为 1 天。
  return getProjectActiveDays(project.id) || (project.last_entered_at ? 1 : 0)
}

function buildTrend(
  telemetry: ProjectTelemetry[],
  tasks: RenderTask[],
  rates: BillingRates,
): TrendPoint[] {
  const events = telemetry.flatMap((item) => [
    ...item.videoJobs.map((job) => ({ date: valueDateKey(job.created_at), cost: videoJobCost(job, rates) })),
    ...item.renderJobs.map((job) => ({
      date: valueDateKey(job.created_at),
      cost: numberFrom(job.actual_cost || job.estimated_cost),
    })),
  ])
  const textEvents = tasks.map((task) => ({
    date: valueDateKey(task.created_at),
    cost: taskTokenUsage(task) / 1000 * rates.textPerThousandTokens,
  }))
  const byDate = new Map<string, number>()
  ;[...events, ...textEvents].forEach((event) => {
    if (!event.date) return
    byDate.set(event.date, (byDate.get(event.date) || 0) + event.cost)
  })

  const weekday = ['日', '一', '二', '三', '四', '五', '六']
  return Array.from({ length: 7 }, (_, index) => {
    const date = new Date()
    date.setHours(0, 0, 0, 0)
    date.setDate(date.getDate() - (6 - index))
    const key = dateKey(date)
    return { key, label: `周${weekday[date.getDay()]}`, value: byDate.get(key) || 0 }
  })
}

export default function Home() {
  const navigate = useNavigate()
  const { message } = App.useApp()
  const [projects, setProjects] = useState<Project[]>([])
  const [tasks, setTasks] = useState<RenderTask[]>([])
  const [templatesCount, setTemplatesCount] = useState(0)
  const [telemetry, setTelemetry] = useState<ProjectTelemetry[]>([])
  const [loading, setLoading] = useState(false)
  const [refreshTick, setRefreshTick] = useState(0)
  const [billingRates, setBillingRates] = useState<BillingRates>(readBillingRates)
  const [draftBillingRates, setDraftBillingRates] = useState<BillingRates>(readBillingRates)
  const [billingModalOpen, setBillingModalOpen] = useState(false)

  useEffect(() => {
    let cancelled = false

    async function loadHome() {
      setLoading(true)
      // 兼容旧版本曾保存为 0 的计费参数；刷新首页时重新按默认值/已保存值读取。
      setBillingRates(readBillingRates())
      try {
        const [projectResponse, taskResponse] = await Promise.all([
          projectApi.list({ page_size: 100 }),
          taskApi.list({}),
        ])
        const nextProjects = projectResponse.data.items
        if (cancelled) return
        setProjects(nextProjects)
        setTasks(taskResponse.data)

        const [templateResponse, telemetryResponse] = await Promise.all([
          nextProjects[0]
            ? videoGenApi.templates(nextProjects[0].id).then((response) => response.data).catch(() => [])
            : Promise.resolve([]),
          Promise.all(
            nextProjects.map(async (project) => {
              const [videoResponse, renderResponse] = await Promise.all([
                videoGenApi.listTasks(project.id).then((response) => response.data).catch(() => []),
                renderApi.listTasks(project.id).then((response) => response.data).catch(() => []),
              ])
              return {
                projectId: project.id,
                videoJobs: videoResponse,
                renderJobs: renderResponse,
              }
            }),
          ),
        ])
        if (cancelled) return
        setTemplatesCount(templateResponse.length)
        setTelemetry(telemetryResponse)
      } catch {
        if (!cancelled) message.error('首页数据加载失败，请稍后重试')
      } finally {
        if (!cancelled) setLoading(false)
      }
    }

    loadHome()
    return () => {
      cancelled = true
    }
  }, [message, refreshTick])

  const telemetryByProject = useMemo(
    () => new Map(telemetry.map((item) => [item.projectId, item])),
    [telemetry],
  )

  const totals = useMemo(() => ({
    projects: projects.length,
    docs: projects.reduce((sum, project) => sum + (project.doc_count || 0), 0),
    shots: projects.reduce((sum, project) => sum + (project.shot_count || 0), 0),
    assets: projects.reduce((sum, project) => sum + (project.asset_count || 0), 0),
  }), [projects])

  const usage = useMemo(() => {
    const videoJobs = telemetry.flatMap((item) => item.videoJobs)
    const renderJobs = telemetry.flatMap((item) => item.renderJobs)
    const videoSeconds = videoJobs
      .filter((job) => job.status !== 'cancelled')
      .reduce((sum, job) => sum + numberFrom(job.duration), 0)
    const videoCost = videoJobs
      .filter((job) => job.status !== 'cancelled')
      .reduce((sum, job) => sum + videoJobCost(job, billingRates), 0)
    const renderCost = renderJobs
      .filter((job) => job.status !== 'cancelled')
      .reduce((sum, job) => sum + numberFrom(job.actual_cost || job.estimated_cost), 0)
    const textTokens = tasks.reduce((sum, task) => sum + taskTokenUsage(task), 0)
    const textCost = textTokens / 1000 * billingRates.textPerThousandTokens
    const activeDays = projects.map(projectActiveDays).filter((days) => days > 0)
    const averageActiveDays = activeDays.length
      ? activeDays.reduce((sum, days) => sum + days, 0) / activeDays.length
      : 0

    return {
      videoJobs,
      renderJobs,
      videoSeconds,
      videoCost,
      renderCost,
      textTokens,
      textCost,
      totalCost: videoCost + renderCost + textCost,
      averageActiveDays,
      activeProjects: activeDays.length,
    }
  }, [billingRates, projects, tasks, telemetry])

  const trend = useMemo(() => buildTrend(telemetry, tasks, billingRates), [billingRates, tasks, telemetry])
  const trendMax = Math.max(...trend.map((point) => point.value), 0)
  const recentlyOpenedProjects = getRecentlyOpenedProjects(projects)
  const focusProject = recentlyOpenedProjects[0] || projects[0]
  const projectOverviewRows = projects.slice(0, 5)
  const activeTaskCount = tasks.filter((task) => ['queued', 'running', 'retry'].includes(task.status)).length
  const failedTaskCount = tasks.filter((task) => task.status === 'failed').length
  const weeklyCost = trend.reduce((sum, point) => sum + point.value, 0)

  const resources = [
    { label: '投标项目', value: totals.projects, icon: <FolderOutlined />, detail: `${usage.activeProjects} 个有活跃记录` },
    { label: '招标资料', value: totals.docs, icon: <FileTextOutlined />, detail: '已归档项目文件' },
    { label: '解说词分镜', value: totals.shots, icon: <VideoCameraOutlined />, detail: '已拆解视频镜头' },
    { label: '素材文件', value: totals.assets, icon: <PictureOutlined />, detail: '可复用画面与音频' },
  ]

  function openBillingModal() {
    setDraftBillingRates(billingRates)
    setBillingModalOpen(true)
  }

  function saveBillingRates() {
    const nextRates: BillingRates = {
      seedancePerSecond: Math.max(0.01, numberFrom(draftBillingRates.seedancePerSecond)),
      textPerThousandTokens: Math.max(0.01, numberFrom(draftBillingRates.textPerThousandTokens)),
    }
    setBillingRates(nextRates)
    setDraftBillingRates(nextRates)
    window.localStorage.setItem(BILLING_RATES_KEY, JSON.stringify(nextRates))
    setBillingModalOpen(false)
    message.success('计费基准已保存，首页数据已重新计算')
  }

  return (
    <main className="home-page" aria-busy={loading}>
      <header className="home-header">
        <div className="home-heading">
          <Title level={2}>项目总览</Title>
        </div>
        <Space className="home-header-actions">
          <Button
            icon={<ReloadOutlined />}
            onClick={() => setRefreshTick((tick) => tick + 1)}
            loading={loading}
          >
            刷新
          </Button>
          <Button type="primary" icon={<SettingOutlined />} onClick={openBillingModal}>
            计费设置
          </Button>
        </Space>
      </header>

      <section className="home-overview-grid" aria-label="项目概览">
        <div className="home-project-focus">
          {loading && !focusProject ? (
            <Skeleton active title={{ width: '56%' }} paragraph={{ rows: 3 }} />
          ) : focusProject ? (
            <>
              <div className="home-project-focus-copy">
                <div className="home-section-label">继续上次项目</div>
                <div className="home-project-focus-title-row">
                  <h2>{focusProject.name}</h2>
                  <Tag color={focusProject.status === 'active' ? 'green' : 'default'}>
                    {focusProject.status === 'active' ? '进行中' : '草稿'}
                  </Tag>
                </div>
                <div className="home-project-focus-meta">
                  <span>{focusProject.code || '未设置招标编号'}</span>
                  <span>最近进入 {projectVisitTime(focusProject.last_entered_at)}</span>
                </div>
                <p>{focusProject.description || '继续整理招标资料、解说词与项目成片。'}</p>
                <Space wrap>
                  <Button type="primary" onClick={() => navigate(`/project/${focusProject.id}`)}>
                    继续项目 <ArrowRightOutlined />
                  </Button>
                  <Button onClick={() => navigate('/projects')}>所有项目</Button>
                </Space>
              </div>
              <div className="home-project-focus-stats" aria-label="当前项目资源">
                {[
                  { label: '资料', value: focusProject.doc_count || 0 },
                  { label: '分镜', value: focusProject.shot_count || 0 },
                  { label: '素材', value: focusProject.asset_count || 0 },
                  { label: '活跃天数', value: projectActiveDays(focusProject) || 0 },
                ].map((item) => (
                  <div key={item.label}>
                    <strong>{item.value}</strong>
                    <span>{item.label}</span>
                  </div>
                ))}
              </div>
            </>
          ) : (
            <div className="home-project-focus-copy home-project-empty">
              <div className="home-section-label">开始使用</div>
              <h2>创建第一个投标项目</h2>
              <p>从招标资料开始，逐步完成解说词、分镜、配音与成片。</p>
              <Button type="primary" onClick={() => navigate('/projects')}>
                前往项目管理 <ArrowRightOutlined />
              </Button>
            </div>
          )}
        </div>

        <aside className="home-cost-summary" aria-label="AI 成本摘要">
          <div className="home-cost-summary-head">
            <div>
              <span>累计 AI 成本估算</span>
              <strong>{currency(usage.totalCost)}</strong>
            </div>
            <span className="home-cost-icon"><DollarOutlined /></span>
          </div>
          <div className="home-cost-summary-secondary">
            <div>
              <span>近 7 天</span>
              <b>{currency(weeklyCost)}</b>
            </div>
            <div>
              <span>视频生成</span>
              <b>{usage.videoSeconds || 0} 秒</b>
            </div>
          </div>
          <p>按当前浏览器中的计费基准估算，不代表实际账单。</p>
        </aside>
      </section>

      <section className="home-resource-strip" aria-label="全局资源概览">
        {resources.map((item) => (
          <div className="home-resource-stat" key={item.label}>
            <span className="home-resource-stat-icon">{item.icon}</span>
            <div>
              <strong>{item.value}</strong>
              <span>{item.label}</span>
              <small>{item.detail}</small>
            </div>
          </div>
        ))}
      </section>

      <section className="home-workspace-grid">
        <Card
          className="home-panel home-project-panel"
          title="项目推进情况"
          extra={<Button type="link" onClick={() => navigate('/projects')}>管理项目 <ArrowRightOutlined /></Button>}
        >
          {loading && projectOverviewRows.length === 0 ? (
            <div className="home-project-list-loading">
              <Skeleton active title={false} paragraph={{ rows: 4 }} />
            </div>
          ) : projectOverviewRows.length > 0 ? (
            <div className="home-project-list">
              {projectOverviewRows.map((project) => {
                const activeDays = projectActiveDays(project)
                return (
                  <button
                    type="button"
                    className="home-project-row"
                    key={project.id}
                    onClick={() => navigate(`/project/${project.id}`)}
                  >
                    <span className="home-project-row-main">
                      <b>{project.name}</b>
                      <small>{project.code || '未设置招标编号'}</small>
                    </span>
                    <span className="home-project-row-resources">
                      <span><b>{project.doc_count || 0}</b> 资料</span>
                      <span><b>{project.shot_count || 0}</b> 分镜</span>
                      <span><b>{project.asset_count || 0}</b> 素材</span>
                    </span>
                    <span className="home-project-row-cost">
                      <small>成本估算</small>
                      <b>{currency(projectCost(telemetryByProject.get(project.id), billingRates))}</b>
                    </span>
                    <span className="home-project-row-activity">
                      <small>{activeDays ? `活跃 ${activeDays} 天` : '暂无活跃记录'}</small>
                      <ArrowRightOutlined />
                    </span>
                  </button>
                )
              })}
            </div>
          ) : (
            <div className="home-project-list-empty">
              <FolderOutlined />
              <div>
                <b>还没有项目</b>
                <span>创建项目后，推进数据会显示在这里。</span>
              </div>
              <Button onClick={() => navigate('/projects')}>项目管理</Button>
            </div>
          )}
        </Card>

        <Card
          className="home-panel home-task-panel"
          title="AI 任务动态"
          extra={<span className="home-template-count"><AppstoreOutlined /> 模板 {templatesCount}</span>}
        >
          <div className="home-task-summary-grid">
            <div className="is-primary">
              <ThunderboltOutlined />
              <span>进行中</span>
              <strong>{activeTaskCount}</strong>
            </div>
            <div className={failedTaskCount > 0 ? 'has-error' : ''}>
              <span>失败待重试</span>
              <strong>{failedTaskCount}</strong>
            </div>
            <div>
              <ClockCircleOutlined />
              <span>平均活跃</span>
              <strong>{usage.averageActiveDays ? `${usage.averageActiveDays.toFixed(1)} 天` : '待记录'}</strong>
            </div>
          </div>

          <div className="home-task-list">
            {tasks.length === 0 && <div className="home-task-empty">暂无任务记录</div>}
            {tasks.slice(0, 5).map((task) => (
              <div key={task.id} className="home-task-row">
                <span>{taskTypeLabel(task.task_type)}</span>
                <TaskTag status={task.status} />
              </div>
            ))}
          </div>

          <div className="home-activity-week" aria-label="最近七天项目活跃情况">
            <span>最近 7 天活跃</span>
            <div>
              {Array.from({ length: 7 }, (_, index) => {
                const date = new Date()
                date.setHours(0, 0, 0, 0)
                date.setDate(date.getDate() - (6 - index))
                const hasActivity = projects.some((project) => getProjectActivityDays(project.id).includes(dateKey(date)))
                return <i className={hasActivity ? 'is-active' : ''} key={dateKey(date)} title={dateKey(date)} />
              })}
            </div>
          </div>
        </Card>
      </section>

      <Card
        className="home-panel home-insights-panel"
        title="AI 使用与成本"
        extra={<Tag color="blue">估算数据</Tag>}
      >
        <div className="home-insights-grid">
          <div className="home-trend-section">
            <div className="home-panel-intro">
              <div>
                <b>近 7 天成本趋势</b>
                <span>每日 AI 视频、画面渲染和文字处理的估算合计</span>
              </div>
              <strong>{currency(weeklyCost)}</strong>
            </div>
            <div className="home-chart" role="img" aria-label="近七天 AI 成本趋势柱状图">
              <div className="home-chart-axis">
                <span>{currency(trendMax)}</span>
                <span>¥0</span>
              </div>
              <div className="home-chart-bars">
                {trend.map((point) => {
                  const height = trendMax > 0 ? Math.max((point.value / trendMax) * 100, point.value > 0 ? 8 : 0) : 0
                  return (
                    <div className="home-chart-column" key={point.key} title={`${point.key} ${currency(point.value)}`}>
                      <span className="home-chart-value">{point.value > 0 ? currency(point.value) : ''}</span>
                      <div className="home-chart-track">
                        <div className="home-chart-bar" style={{ height: `${height}%` }} />
                      </div>
                      <span className="home-chart-label">{point.label}</span>
                    </div>
                  )
                })}
              </div>
              {trendMax === 0 && (
                <div className="home-chart-empty">完成 AI 任务后，这里会显示每日成本走势</div>
              )}
            </div>
          </div>

          <aside className="home-breakdown-section">
            <div className="home-panel-intro">
              <div>
                <b>累计成本构成</b>
                <span>基于已记录任务用量</span>
              </div>
              <strong>{currency(usage.totalCost)}</strong>
            </div>
            <div className="home-breakdown-list">
              {[
                { label: 'AI 视频生成', value: usage.videoCost, detail: `${usage.videoSeconds || 0} 秒` },
                { label: '画面渲染', value: usage.renderCost, detail: `${usage.renderJobs.length} 个任务` },
                { label: '文字 Token', value: usage.textCost, detail: `${compactNumber(usage.textTokens)} tokens` },
              ].map((item) => {
                const percent = usage.totalCost > 0 ? (item.value / usage.totalCost) * 100 : 0
                return (
                  <div className="home-breakdown-item" key={item.label}>
                    <span className="home-breakdown-index" />
                    <div>
                      <b>{item.label}</b>
                      <small>{item.detail}，占比 {percent.toFixed(0)}%</small>
                    </div>
                    <strong>{currency(item.value)}</strong>
                  </div>
                )
              })}
            </div>
          </aside>
        </div>
      </Card>

      <Modal
        title="计费基准"
        open={billingModalOpen}
        onCancel={() => setBillingModalOpen(false)}
        onOk={saveBillingRates}
        okText="保存基准"
        cancelText="取消"
        destroyOnHidden
      >
        <div className="billing-modal-intro">
          设置后会立即影响首页成本卡片、趋势图和项目成本估算。价格保存在当前浏览器中。
        </div>
        <div className="billing-modal-fields">
          <label>
            <span>Seedance 2.0 视频单价</span>
            <InputNumber
              value={draftBillingRates.seedancePerSecond}
              min={0.01}
              step={0.01}
              precision={2}
              addonAfter="元 / 秒"
              style={{ width: '100%' }}
              onChange={(value) => setDraftBillingRates((current) => ({
                ...current,
                seedancePerSecond: value ?? 0,
              }))}
            />
          </label>
          <label>
            <span>文字 Token 单价</span>
            <InputNumber
              value={draftBillingRates.textPerThousandTokens}
              min={0.01}
              step={0.01}
              precision={2}
              addonAfter="元 / 1k tokens"
              style={{ width: '100%' }}
              onChange={(value) => setDraftBillingRates((current) => ({
                ...current,
                textPerThousandTokens: value ?? 0,
              }))}
            />
          </label>
        </div>
        <div className="billing-modal-footer">
          <span>默认值：¥{DEFAULT_BILLING_RATES.seedancePerSecond.toFixed(2)}/秒，¥{DEFAULT_BILLING_RATES.textPerThousandTokens.toFixed(2)}/1k tokens</span>
          <Button type="link" size="small" onClick={() => setDraftBillingRates(DEFAULT_BILLING_RATES)}>
            恢复默认值
          </Button>
        </div>
      </Modal>
    </main>
  )
}
