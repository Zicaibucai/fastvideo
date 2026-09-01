import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react'
import type { ReactNode } from 'react'
import { Button, Typography } from 'antd'
import { ReloadOutlined } from '@ant-design/icons'
import { useNavigate } from 'react-router-dom'
import {
  exportApi,
  factApi,
  notificationApi,
  renderApi,
  taskApi,
  videoGenApi,
  voiceApi,
} from '../api'
import type {
  ExportTask,
  ExtractedFact,
  AppNotification,
  RenderJobTask,
  RenderTask,
  VideoGenerationJob,
  VoiceJob,
} from '../api/types'
import FloatingNoticeCenter from './FloatingNoticeCenter'
import type { NoticeItem, NoticeTone } from './FloatingNoticeCenter'

const { Text } = Typography

interface ProjectNoticeContextValue {
  notices: NoticeItem[]
  upsertNotice: (notice: NoticeItem) => void
  removeNotice: (key: string) => void
}

const ProjectNoticeContext = createContext<ProjectNoticeContextValue | null>(null)

export function ProjectNotificationProvider({
  children,
}: {
  children: ReactNode
}) {
  const [manualNotices, setManualNotices] = useState<Record<string, NoticeItem>>({})

  const upsertNotice = useCallback((notice: NoticeItem) => {
    setManualNotices((current) => ({ ...current, [notice.key]: notice }))
  }, [])

  const removeNotice = useCallback((key: string) => {
    setManualNotices((current) => {
      if (!current[key]) return current
      const next = { ...current }
      delete next[key]
      return next
    })
  }, [])

  const value = useMemo<ProjectNoticeContextValue>(() => ({
    notices: Object.values(manualNotices),
    upsertNotice,
    removeNotice,
  }), [manualNotices, removeNotice, upsertNotice])

  return (
    <ProjectNoticeContext.Provider value={value}>
      {children}
    </ProjectNoticeContext.Provider>
  )
}

export function useProjectNotifications() {
  const context = useContext(ProjectNoticeContext)
  if (!context) {
    throw new Error('useProjectNotifications must be used inside ProjectNotificationProvider')
  }
  return context
}

type TaskSource = 'task' | 'video' | 'render' | 'voice' | 'export'

interface ProjectTaskNotice {
  key: string
  source: TaskSource
  taskId: string
  label: string
  status: string
  progress?: number
  message?: string
  errorMessage?: string
  createdAt?: string
  updatedAt?: string
  route: string
  retry?: () => Promise<unknown>
  cancel?: () => Promise<unknown>
  regenerate?: () => Promise<unknown>
}

const ACTIVE_STATUSES = new Set([
  'pending',
  'queued',
  'running',
  'retry',
  'processing',
  'in_progress',
])

const FAILED_STATUSES = new Set(['failed', 'error', 'cancelled', 'canceled'])
const SUCCESS_STATUSES = new Set(['success', 'completed', 'complete', 'done'])

const TASK_LABELS: Record<string, string> = {
  parse_document: '文档解析',
  gen_narration: '解说词生成',
  gen_image: 'AI 图片生成',
  gen_tts: '配音生成',
  gen_video: 'AI 视频生成',
  gen_voice_version: '配音版本生成',
  tts_batch: '批量配音',
  segment_render: '分段渲染',
  segment_render_all: '批量渲染',
  export: '视频导出',
}

function isActive(status: string) {
  return ACTIVE_STATUSES.has(status.toLowerCase())
}

function isFailed(status: string) {
  return FAILED_STATUSES.has(status.toLowerCase())
}

function isSuccessful(status: string) {
  return SUCCESS_STATUSES.has(status.toLowerCase())
}

function isVisibleStatus(status: string, timestamp?: string) {
  const normalized = status.toLowerCase()
  if (isActive(normalized)) return true
  if (!isFailed(normalized) && !isSuccessful(normalized)) return true
  if (!timestamp) return isFailed(normalized)
  const age = Date.now() - new Date(timestamp).getTime()
  if (Number.isNaN(age)) return isFailed(normalized)
  return isFailed(normalized) ? age < 24 * 60 * 60 * 1000 : age < 10 * 60 * 1000
}

function taskRoute(taskType: string, projectId: string) {
  if (taskType === 'gen_narration') return `/project/${projectId}/storyboard`
  if (taskType === 'parse_document') return `/project/${projectId}/reader`
  if (['gen_tts', 'gen_voice_version', 'tts_batch'].includes(taskType)) {
    return `/project/${projectId}/voice`
  }
  if (taskType === 'gen_image') return `/project/${projectId}/render`
  if (taskType === 'gen_video') return `/project/${projectId}/ai-video`
  if (taskType === 'export') return `/project/${projectId}/video`
  if (taskType.startsWith('segment_render')) return `/project/${projectId}/video`
  return `/project/${projectId}`
}

function genericTaskToNotice(task: RenderTask, projectId: string): ProjectTaskNotice {
  const label = TASK_LABELS[task.task_type] || '后台任务'
  return {
    key: `task:${task.id}`,
    source: 'task',
    taskId: task.id,
    label,
    status: task.status,
    progress: task.progress,
    message: task.message,
    errorMessage: task.error_message,
    createdAt: task.created_at,
    updatedAt: task.updated_at,
    route: taskRoute(task.task_type, projectId),
    retry: () => taskApi.retry(task.id),
  }
}

function videoTaskToNotice(task: VideoGenerationJob, projectId: string): ProjectTaskNotice {
  return {
    key: `video:${task.id}`,
    source: 'video',
    taskId: task.id,
    label: 'AI 视频生成',
    status: task.status,
    progress: task.progress,
    errorMessage: task.error_message,
    createdAt: task.created_at,
    updatedAt: task.completed_at || task.created_at,
    route: `/project/${projectId}/ai-video`,
    retry: () => videoGenApi.retryTask(projectId, task.id),
    cancel: () => videoGenApi.cancelTask(projectId, task.id),
    regenerate: () => videoGenApi.regenerateTask(projectId, task.id),
  }
}

function renderTaskToNotice(task: RenderJobTask, projectId: string): ProjectTaskNotice {
  return {
    key: `render:${task.id}`,
    source: 'render',
    taskId: task.id,
    label: '画面制作',
    status: task.status,
    progress: task.progress,
    errorMessage: task.error_message,
    createdAt: typeof task.created_at === 'string' ? task.created_at : undefined,
    route: `/project/${projectId}/render`,
    retry: () => renderApi.retryTask(projectId, task.id),
  }
}

function voiceTaskToNotice(task: VoiceJob, projectId: string): ProjectTaskNotice {
  return {
    key: `voice:${task.id}`,
    source: 'voice',
    taskId: task.id,
    label: task.task_type === 'tts_batch' ? '批量配音' : '配音制作',
    status: task.status,
    progress: task.progress,
    message: task.message,
    errorMessage: task.error_message,
    createdAt: task.created_at,
    updatedAt: task.updated_at,
    route: `/project/${projectId}/voice`,
    retry: () => voiceApi.retryJob(projectId, task.id),
  }
}

function exportTaskToNotice(task: ExportTask, projectId: string): ProjectTaskNotice {
  return {
    key: `export:${task.id}`,
    source: 'export',
    taskId: task.id,
    label: '视频导出',
    status: task.status,
    progress: task.progress,
    errorMessage: task.error_message,
    createdAt: task.created_at,
    route: `/project/${projectId}/video`,
    retry: () => exportApi.retry(task.id),
  }
}

function noticeTone(status: string): NoticeTone {
  const normalized = status.toLowerCase()
  if (isFailed(normalized)) return normalized === 'cancelled' || normalized === 'canceled' ? 'warning' : 'error'
  if (isSuccessful(normalized)) return 'success'
  return 'info'
}

function appNotificationTone(type: string): NoticeTone {
  const normalized = type.toLowerCase()
  if (normalized.includes('fail') || normalized.includes('error')) return 'error'
  if (normalized.includes('accept') || normalized.includes('complete')) return 'success'
  if (normalized.includes('review') || normalized.includes('approve')) return 'warning'
  return 'info'
}

function noticeTitle(task: ProjectTaskNotice) {
  const normalized = task.status.toLowerCase()
  if (isFailed(normalized)) return normalized === 'cancelled' || normalized === 'canceled' ? `${task.label}已取消` : `${task.label}失败`
  if (isSuccessful(normalized)) return `${task.label}已完成`
  return `${task.label}进行中`
}

function noticeDescription(task: ProjectTaskNotice) {
  const normalized = task.status.toLowerCase()
  if (isFailed(normalized)) return task.errorMessage || '任务未能完成，可重试或进入对应页面查看详情。'
  if (isSuccessful(normalized)) return '任务已完成，结果可以在对应工作区查看。'
  if (task.message) return task.message
  if (typeof task.progress === 'number') return `已完成 ${Math.round(task.progress)}%，可以继续浏览其他页面。`
  return '任务正在后台处理，可以继续浏览其他页面。'
}

function sourceRank(source: TaskSource) {
  return { task: 0, video: 1, render: 2, voice: 3, export: 4 }[source]
}

function taskIdentity(task: RenderTask) {
  // 同一份文档可能因为重试、切换解析策略产生多条 RenderTask。
  // 通知中心只应该展示该文档最新的一条，避免旧的 running/0% 任务永久残留。
  if (task.task_type === 'parse_document') {
    // 新版接口按文档区分；旧版接口未返回 params 时先按项目合并，
    // 至少保证旧的解析任务不会盖住最新结果。
    return `parse_document:${task.params?.doc_id || 'project-latest'}`
  }
  if (task.shot_id) {
    // 解说词、画面生成、分段渲染等任务可能对同一分镜重复提交。
    // 同一分镜只保留最新任务，避免旧的 queued/running 通知长期残留。
    return `${task.task_type}:shot:${task.shot_id}`
  }
  return `task:${task.id}`
}

function latestGenericTasks(tasks: RenderTask[]) {
  const latest = new Map<string, RenderTask>()
  for (const task of tasks) {
    const key = taskIdentity(task)
    const previous = latest.get(key)
    if (!previous) {
      latest.set(key, task)
      continue
    }
    const currentTime = new Date(task.created_at).getTime()
    const previousTime = new Date(previous.created_at).getTime()
    if (currentTime >= previousTime) latest.set(key, task)
  }
  return [...latest.values()]
}

export default function ProjectNotificationCenter({ projectId }: { projectId: string | null }) {
  const navigate = useNavigate()
  const { notices: manualNotices } = useProjectNotifications()
  const [appNotifications, setAppNotifications] = useState<AppNotification[]>([])
  const [taskNotices, setTaskNotices] = useState<ProjectTaskNotice[]>([])
  const [factCounts, setFactCounts] = useState({ conflict: 0, unverified: 0 })
  const [retryingKey, setRetryingKey] = useState<string | null>(null)

  const refreshAppNotifications = useCallback(async () => {
    if (document.visibilityState !== 'visible') return
    try {
      const response = await notificationApi.list({ limit: 20 })
      setAppNotifications(response.data)
    } catch {
      // 通知中心不能影响页面主流程，接口暂时不可用时保留上次结果。
    }
  }, [])

  useEffect(() => {
    void refreshAppNotifications()
    const timer = window.setInterval(() => void refreshAppNotifications(), 30000)
    const refresh = () => void refreshAppNotifications()
    document.addEventListener('visibilitychange', refresh)
    return () => {
      window.clearInterval(timer)
      document.removeEventListener('visibilitychange', refresh)
    }
  }, [refreshAppNotifications])

  const openAppNotification = useCallback(async (item: AppNotification) => {
    if (!item.is_read) {
      setAppNotifications((current) => current.map((candidate) => (
        candidate.id === item.id ? { ...candidate, is_read: true } : candidate
      )))
      try {
        await notificationApi.markRead(item.id)
      } catch {
        setAppNotifications((current) => current.map((candidate) => (
          candidate.id === item.id ? { ...candidate, is_read: false } : candidate
        )))
      }
    }
    if (item.link) navigate(item.link)
  }, [navigate])

  const markAllAppNotificationsRead = useCallback(async () => {
    setAppNotifications((current) => current.map((item) => ({ ...item, is_read: true })))
    try {
      await notificationApi.markAllRead()
    } catch {
      await refreshAppNotifications()
    }
  }, [refreshAppNotifications])

  const fetchTasks = useCallback(async () => {
    if (!projectId) {
      setTaskNotices([])
      setFactCounts({ conflict: 0, unverified: 0 })
      return
    }
    const results = await Promise.allSettled([
      taskApi.list({ project_id: projectId }),
      videoGenApi.listTasks(projectId),
      renderApi.listTasks(projectId),
      voiceApi.jobs(projectId),
      exportApi.list(projectId),
      factApi.list(projectId),
    ])

    const valueAt = <T,>(index: number): T[] => {
      const result = results[index]
      return result?.status === 'fulfilled' ? result.value.data as unknown as T[] : []
    }

    const genericTasks = latestGenericTasks(valueAt<RenderTask>(0)).map((task) => genericTaskToNotice(task, projectId))
    const videoTasks = valueAt<VideoGenerationJob>(1).map((task) => videoTaskToNotice(task, projectId))
    const renderTasks = valueAt<RenderJobTask>(2).map((task) => renderTaskToNotice(task, projectId))
    const voiceTasks = valueAt<VoiceJob>(3).map((task) => voiceTaskToNotice(task, projectId))
    const exports = valueAt<ExportTask>(4).map((task) => exportTaskToNotice(task, projectId))
    const facts = valueAt<ExtractedFact>(5)

    setFactCounts({
      conflict: facts.filter((fact) => fact.verification_status === 'conflict').length,
      // 高置信度候选已经可以供 AI 使用，不再作为“待确认”通知反复提醒。
      unverified: facts.filter(
        (fact) => fact.verification_status === 'unverified' && fact.usage_status === 'review',
      ).length,
    })

    const visible = [...genericTasks, ...videoTasks, ...renderTasks, ...voiceTasks, ...exports]
      .filter((task) => isVisibleStatus(task.status, task.updatedAt || task.createdAt))
      .sort((a, b) => {
        const aTime = new Date(a.updatedAt || a.createdAt || 0).getTime()
        const bTime = new Date(b.updatedAt || b.createdAt || 0).getTime()
        return bTime - aTime || sourceRank(a.source) - sourceRank(b.source)
      })

    setTaskNotices(visible)
  }, [projectId])

  useEffect(() => {
    let cancelled = false
    const refresh = () => {
      if (!cancelled && document.visibilityState === 'visible') void fetchTasks()
    }
    refresh()
    // Notifications are informative rather than latency-critical. Poll less
    // aggressively and pause while the tab is hidden to avoid multiplying six
    // API requests by every open project page.
    const timer = window.setInterval(refresh, 10000)
    document.addEventListener('visibilitychange', refresh)
    return () => {
      cancelled = true
      window.clearInterval(timer)
      document.removeEventListener('visibilitychange', refresh)
    }
  }, [fetchTasks])

  const appItems = useMemo<NoticeItem[]>(() => appNotifications.map((item) => ({
    key: `app:${item.id}`,
    tone: appNotificationTone(item.type),
    title: item.title,
    description: item.body,
    read: item.is_read,
    createdAt: item.created_at,
    onOpen: () => openAppNotification(item),
  })), [appNotifications, openAppNotification])

  const items = useMemo<NoticeItem[]>(() => {
    const factItems: NoticeItem[] = []

    if (factCounts.conflict > 0) {
      factItems.push({
        key: 'facts:conflict',
        tone: 'warning',
        title: `${factCounts.conflict} 条参数存在来源冲突`,
        description: '同一参数在不同文件中数值不一致，需要人工确认最终采用值。',
        action: (
          <Button size="small" onClick={() => navigate(`/project/${projectId}/facts`)}>
            查看参数台账
          </Button>
        ),
      })
    }

    if (factCounts.unverified > 0) {
      factItems.push({
        key: 'facts:unverified',
        tone: 'info',
        title: `${factCounts.unverified} 条参数待审核`,
        description: '置信度在60%–80%的参数需要确认；低于60%的数字会自动排除，高于80%的参数可供 AI 草稿使用。',
        action: (
          <Button size="small" onClick={() => navigate(`/project/${projectId}/facts`)}>
            查看参数台账
          </Button>
        ),
      })
    }

    const taskItems = taskNotices.map<NoticeItem>((task) => ({
      key: task.key,
      tone: noticeTone(task.status),
      title: noticeTitle(task),
      description: <Text type="secondary">{noticeDescription(task)}</Text>,
      progress: isActive(task.status) && typeof task.progress === 'number' ? task.progress : undefined,
      createdAt: task.updatedAt || task.createdAt,
      action: (
        <span className="notice-center-actions">
          <Button size="small" onClick={() => navigate(task.route)}>进入查看</Button>
          {isFailed(task.status) && task.retry && (
            <Button
              size="small"
              type="primary"
              ghost
              icon={<ReloadOutlined />}
              loading={retryingKey === task.key}
              onClick={async () => {
                setRetryingKey(task.key)
                try {
                  await task.retry?.()
                  await fetchTasks()
                } finally {
                  setRetryingKey(null)
                }
              }}
            >
              重试
            </Button>
          )}
          {isActive(task.status) && task.cancel && (
            <Button size="small" danger onClick={async () => { await task.cancel?.(); await fetchTasks() }}>
              取消
            </Button>
          )}
          {isSuccessful(task.status) && task.source === 'video' && task.regenerate && (
            <Button size="small" onClick={async () => { await task.regenerate?.(); await fetchTasks() }}>
              重新生成
            </Button>
          )}
        </span>
      ),
    }))

    return [...appItems, ...manualNotices, ...factItems, ...taskItems]
  }, [appItems, factCounts, fetchTasks, manualNotices, navigate, projectId, retryingKey, taskNotices])

  return <FloatingNoticeCenter items={items} onMarkAllRead={markAllAppNotificationsRead} />
}
