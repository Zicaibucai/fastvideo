import { act, renderHook } from '@testing-library/react'
import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest'
import { videoGenApi } from '../api'
import { useAiVideoData } from './useAiVideoData'

const mocks = vi.hoisted(() => ({
  templates: vi.fn(),
  referenceImages: vi.fn(),
  versions: vi.fn(),
  providers: vi.fn(),
  getTask: vi.fn(),
}))

vi.mock('../api', () => ({ videoGenApi: mocks }))

describe('useAiVideoData', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    mocks.templates.mockResolvedValue({ data: [] })
    mocks.referenceImages.mockResolvedValue({ data: [] })
    mocks.versions.mockResolvedValue({ data: [] })
    mocks.providers.mockResolvedValue({ data: [] })
    mocks.getTask.mockReset()
  })

  afterEach(() => {
    vi.runOnlyPendingTimers()
    vi.useRealTimers()
  })

  it('cleans up task polling when the page unmounts', async () => {
    let resolveTask!: (value: { data: { id: string; status: 'running' } }) => void
    mocks.getTask.mockReturnValue(new Promise((resolve) => { resolveTask = resolve }))
    const onTaskComplete = vi.fn()
    const { result, unmount } = renderHook(() => useAiVideoData({
      projectId: 'project-1',
      selectedProvider: 'seedance',
      onTaskComplete,
    }))

    act(() => {
      result.current.setActiveJobId('job-1')
    })
    await act(async () => { await Promise.resolve() })
    expect(mocks.getTask).toHaveBeenCalledTimes(1)

    unmount()
    resolveTask({ data: { id: 'job-1', status: 'running' } })
    await act(async () => {
      await Promise.resolve()
      vi.advanceTimersByTime(5000)
      await Promise.resolve()
    })

    expect(mocks.getTask).toHaveBeenCalledTimes(1)
    expect(onTaskComplete).not.toHaveBeenCalled()
  })
})
