import { useEffect, useRef, useState } from 'react'
import { Tag, Space, Button } from 'antd'
import { ReloadOutlined } from '@ant-design/icons'
import { taskApi } from '../api'
import type { RenderTask } from '../api/types'

const STATUS_MAP: Record<string, { color: string; label: string }> = {
  queued: { color: 'blue', label: '排队中' },
  running: { color: 'processing', label: '处理中' },
  success: { color: 'success', label: '成功' },
  failed: { color: 'error', label: '失败' },
  retry: { color: 'warning', label: '重试中' },
  cancelled: { color: 'default', label: '已取消' },
}

const TASK_TYPE_LABEL: Record<string, string> = {
  parse_document: '资料解析',
  gen_narration: '解说词生成',
  gen_image: '画面生成',
  gen_video: '视频生成',
  gen_tts: 'AI配音',
  gen_voice_version: '配音版本生成',
  tts_batch: '批量配音',
  segment_render: '分段渲染',
  segment_render_all: '批量分段渲染',
  compose_video: '视频合成',
  export: '视频导出',
}

export function TaskTag({ status }: { status: string }) {
  const item = STATUS_MAP[status] || { color: 'default', label: status }
  return <Tag color={item.color}>{item.label}</Tag>
}

export function taskTypeLabel(type: string) {
  return TASK_TYPE_LABEL[type] || type
}

/** 轮询任务状态直到终态 */
export function useTaskPolling(
  taskId: string | null,
  onDone?: (task: RenderTask) => void,
  intervalMs = 1500,
) {
  const [task, setTask] = useState<RenderTask | null>(null)

  useEffect(() => {
    if (!taskId) return
    let stop = false
    let timer: ReturnType<typeof setInterval>

    const tick = async () => {
      try {
        const res = await taskApi.detail(taskId)
        if (stop) return
        setTask(res.data)
        if (['success', 'failed', 'cancelled'].includes(res.data.status)) {
          clearInterval(timer)
          onDone?.(res.data)
        }
      } catch {
        // 忽略瞬时错误
      }
    }

    tick()
    timer = setInterval(tick, intervalMs)
    return () => {
      stop = true
      clearInterval(timer)
    }
  }, [taskId, intervalMs])

  return task
}

/** 手动触发一个任务并轮询，提供状态展示 */
export function useRunTask() {
  const [running, setRunning] = useState(false)
  const [status, setStatus] = useState<{ taskId: string; status: string } | null>(null)
  const pollTimer = useRef<ReturnType<typeof setInterval> | null>(null)
  const mounted = useRef(true)

  useEffect(() => () => {
    mounted.current = false
    if (pollTimer.current) clearInterval(pollTimer.current)
  }, [])

  const run = (promise: Promise<{ data: { task_id: string } }>, onDone?: (t: RenderTask) => void) => {
    if (pollTimer.current) clearInterval(pollTimer.current)
    setRunning(true)
    setStatus(null)
    promise
      .then((res) => {
        if (!mounted.current) return null
        setStatus({ taskId: res.data.task_id, status: 'queued' })
        return res.data.task_id
      })
      .then((taskId) => {
        if (!taskId || !mounted.current) return
        // 轮询
        const poll = setInterval(() => {
          taskApi.detail(taskId).then((r) => {
            if (!mounted.current) return
            setStatus({ taskId, status: r.data.status })
            if (['success', 'failed', 'cancelled'].includes(r.data.status)) {
              clearInterval(poll)
              pollTimer.current = null
              setRunning(false)
              onDone?.(r.data)
            }
          }).catch(() => {})
        }, 1500)
        pollTimer.current = poll
      })
      .catch(() => {
        if (pollTimer.current) clearInterval(pollTimer.current)
        pollTimer.current = null
        setRunning(false)
      })
  }

  return { run, running, status }
}

export function StatusBar({ taskId, status, onRetry }: { taskId?: string; status?: string; onRetry?: () => void }) {
  if (!taskId || !status) return null
  const item = STATUS_MAP[status] || { color: 'default', label: status }
  return (
    <Space>
      <Tag color={item.color}>{item.label}</Tag>
      {status === 'failed' && onRetry && (
        <Button size="small" icon={<ReloadOutlined />} onClick={onRetry}>
          重试
        </Button>
      )}
    </Space>
  )
}
