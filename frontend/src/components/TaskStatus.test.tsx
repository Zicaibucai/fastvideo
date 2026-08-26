import { act, render, renderHook, screen } from '@testing-library/react'
import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest'
import { taskApi } from '../api'
import type { RenderTask } from '../api/types'
import { StatusBar, TaskTag, useRunTask, useTaskPolling } from './TaskStatus'

vi.mock('../api', () => ({
  taskApi: { detail: vi.fn() },
}))

const detail = vi.mocked(taskApi.detail)

const task: RenderTask = {
  id: 'task-1',
  task_type: 'gen_video',
  status: 'running',
  progress: 25,
  attempts: 1,
  max_attempts: 3,
  created_at: '2026-08-26T00:00:00Z',
  updated_at: '2026-08-26T00:00:00Z',
}

describe('TaskStatus', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    detail.mockReset()
  })

  afterEach(() => {
    vi.runOnlyPendingTimers()
    vi.useRealTimers()
  })

  it('stops polling and ignores late responses after unmount', async () => {
    detail.mockResolvedValue({ data: task })
    const { unmount } = renderHook(() => useTaskPolling('task-1', undefined, 100))

    await act(async () => {
      await Promise.resolve()
    })
    expect(detail).toHaveBeenCalledTimes(1)

    unmount()
    await act(async () => {
      vi.advanceTimersByTime(500)
      await Promise.resolve()
    })
    expect(detail).toHaveBeenCalledTimes(1)
  })

  it('clears the run-task timer when the hook unmounts', async () => {
    const { result, unmount } = renderHook(() => useRunTask())
    act(() => {
      result.current.run(Promise.resolve({ data: { task_id: 'task-1' } }))
    })
    await act(async () => {
      await Promise.resolve()
      await Promise.resolve()
    })

    unmount()
    await act(async () => {
      vi.advanceTimersByTime(3000)
      await Promise.resolve()
    })
    expect(detail).not.toHaveBeenCalled()
  })

  it('renders localized status labels and retry action', () => {
    const onRetry = vi.fn()
    render(
      <>
        <TaskTag status="success" />
        <StatusBar taskId="task-1" status="failed" onRetry={onRetry} />
      </>,
    )
    expect(screen.getByText('成功')).toBeInTheDocument()
    act(() => {
      screen.getByRole('button', { name: /重试/ }).click()
    })
    expect(onRetry).toHaveBeenCalledTimes(1)
  })
})
