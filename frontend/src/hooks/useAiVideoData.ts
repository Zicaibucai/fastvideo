import { useCallback, useEffect, useState } from 'react'
import { videoGenApi } from '../api'
import type {
  ReferenceImage,
  TaskStatus,
  VideoGenerationJob,
  VideoProvider,
  VideoGenerationTemplate,
  VideoGenerationVersion,
} from '../api/types'

interface UseAiVideoDataOptions {
  projectId: string
  selectedProvider: string
  onTaskComplete?: (job: VideoGenerationJob) => void
}

const TERMINAL_STATUSES: TaskStatus[] = ['success', 'failed', 'cancelled']

export function useAiVideoData({
  projectId,
  selectedProvider,
  onTaskComplete,
}: UseAiVideoDataOptions) {
  const [refImages, setRefImages] = useState<ReferenceImage[]>([])
  const [templates, setTemplates] = useState<VideoGenerationTemplate[]>([])
  const [versions, setVersions] = useState<VideoGenerationVersion[]>([])
  const [providers, setProviders] = useState<VideoProvider[]>([])
  const [providerCaps, setProviderCaps] = useState<Record<string, boolean>>({})
  const [activeJobId, setActiveJobId] = useState<string | null>(null)
  const [activeJob, setActiveJob] = useState<VideoGenerationJob | null>(null)

  const refresh = useCallback(async () => {
    if (!projectId) return
    try {
      const [templateResponse, imageResponse, versionResponse] = await Promise.all([
        videoGenApi.templates(projectId),
        videoGenApi.referenceImages(projectId),
        videoGenApi.versions(projectId),
      ])
      setTemplates(templateResponse.data)
      setRefImages(imageResponse.data)
      setVersions(versionResponse.data)
    } catch {
      // 错误提示由 API 拦截器统一处理；刷新失败不影响当前编辑状态。
    }
  }, [projectId])

  useEffect(() => {
    void refresh()
  }, [refresh])

  useEffect(() => {
    let cancelled = false
    videoGenApi.providers(projectId)
      .then((response) => {
        if (cancelled) return
        const seedance = (response.data as VideoProvider[]).find((item) => item.provider === 'seedance')
        const list = seedance ? [seedance] : []
        setProviders(list)
        setProviderCaps(seedance?.capabilities || {})
      })
      .catch(() => {})
    return () => {
      cancelled = true
    }
  }, [projectId])

  useEffect(() => {
    const provider = providers.find((item) => item.provider === selectedProvider)
    setProviderCaps(provider?.capabilities || {})
  }, [providers, selectedProvider])

  useEffect(() => {
    if (!activeJobId) return
    let stopped = false
    let timer: ReturnType<typeof setInterval> | undefined
    const tick = async () => {
      try {
        const response = await videoGenApi.getTask(projectId, activeJobId)
        if (stopped) return
        const job = response.data
        setActiveJob(job)
        if (TERMINAL_STATUSES.includes(job.status)) {
          if (timer) clearInterval(timer)
          setActiveJobId(null)
          onTaskComplete?.(job)
          void refresh()
        }
      } catch {
        // 网络瞬时失败时继续轮询。
      }
    }
    void tick()
    timer = setInterval(() => void tick(), 1500)
    return () => {
      stopped = true
      if (timer) clearInterval(timer)
    }
  }, [activeJobId, projectId, onTaskComplete, refresh])

  return {
    activeJob,
    activeJobId,
    providerCaps,
    providers,
    refImages,
    templates,
    versions,
    refresh,
    setActiveJob,
    setActiveJobId,
  }
}
