import api from './client'
import type {
  AiStatus,
  Asset,
  AudioVersion,
  DocumentChunk,
  DocumentPage,
  ExportTask,
  ExtractedFact,
  Page,
  PreflightResult,
  Project,
  PronunciationRule,
  RenderPreset,
  RenderJobTask,
  RenderTask,
  RenderVersion,
  ResumableUpload,
  ScoringCoverage,
  ScoringPoint,
  SearchResult,
  SourceDocument,
  SourceImage,
  StoryboardShot,
  StoryboardSummary,
  SubtitleSegment,
  TocItem,
  User,
  VideoGenerationJob,
  VideoGenerationTemplate,
  VideoGenerationVersion,
  ReferenceImage,
  VideoProject,
  VideoSegment,
  VoiceEstimate,
  VoiceJob,
  VoiceSummary,
  VoiceTemplate,
} from './types'

// ---------- 认证 ----------
export const authApi = {
  login: (email: string, password: string) =>
    api.post<{ access_token: string; token_type: string }>('/auth/login', { email, password }),
  register: (payload: { email: string; username: string; password: string; company?: string }) =>
    api.post<User>('/auth/register', payload),
  me: () => api.get<User>('/auth/me'),
}

// ---------- 系统 ----------
export const systemApi = {
  health: () => api.get('/health'),
  status: () => api.get<{ ai: AiStatus }>('/system/status'),
}

// ---------- 项目 ----------
export const projectApi = {
  list: (params?: { page?: number; page_size?: number; status?: string }) =>
    api.get<Page<Project>>('/projects', { params }),
  create: (payload: { name: string; code?: string; description?: string }) =>
    api.post<Project>('/projects', payload),
  detail: (id: string) => api.get<Project>(`/projects/${id}`),
  update: (id: string, payload: Partial<Project>) => api.patch<Project>(`/projects/${id}`, payload),
  remove: (id: string) => api.delete(`/projects/${id}`),
}

// ---------- 招标资料 ----------
export const documentApi = {
  list: (projectId: string) => api.get<SourceDocument[]>(`/projects/${projectId}/documents`),
  types: () => api.get<Record<string, string>>('/documents/types').catch(() => ({ data: {} })),
  upload: (projectId: string, file: File, docType: string) => {
    const form = new FormData()
    form.append('file', file)
    form.append('doc_type', docType)
    return api.post<SourceDocument>(`/projects/${projectId}/documents`, form)
  },
  createResumableUpload: (projectId: string, payload: { file_name: string; file_size: number; doc_type: string }) =>
    api.post<ResumableUpload>(`/projects/${projectId}/documents/uploads`, payload),
  resumableUploadStatus: (projectId: string, uploadId: string) =>
    api.get<ResumableUpload>(`/projects/${projectId}/documents/uploads/${uploadId}`),
  uploadChunk: (projectId: string, uploadId: string, index: number, chunk: Blob) =>
    api.put<ResumableUpload>(
      `/projects/${projectId}/documents/uploads/${uploadId}/chunks/${index}`,
      chunk,
      { headers: { 'Content-Type': 'application/octet-stream' }, timeout: 180000 },
    ),
  completeResumableUpload: (projectId: string, uploadId: string) =>
    api.post<SourceDocument>(`/projects/${projectId}/documents/uploads/${uploadId}/complete`),
  cancelResumableUpload: (projectId: string, uploadId: string) =>
    api.delete(`/projects/${projectId}/documents/uploads/${uploadId}`),
  search: (projectId: string, q: string) =>
    api.get<SearchResult[]>(`/projects/${projectId}/documents/search`, { params: { q } }),
  reparse: (projectId: string, docId: string) =>
    api.post<SourceDocument>(`/projects/${projectId}/documents/${docId}/parse`),
  updateParams: (projectId: string, docId: string, params: Record<string, any>) =>
    api.put<SourceDocument>(`/projects/${projectId}/documents/${docId}/params`, { params }),
  update: (projectId: string, docId: string, payload: { title?: string; doc_type?: string }) =>
    api.patch<SourceDocument>(`/projects/${projectId}/documents/${docId}`, payload),
  toc: (projectId: string, docId: string) =>
    api.get<TocItem[]>(`/projects/${projectId}/documents/${docId}/toc`),
  remove: (projectId: string, docId: string) =>
    api.delete(`/projects/${projectId}/documents/${docId}`),
}

// ---------- 文档阅读器 ----------
export const readerApi = {
  pages: (projectId: string, docId: string) =>
    api.get<DocumentPage[]>(`/projects/${projectId}/reader/${docId}/pages`),
  page: (projectId: string, docId: string, pageNumber: number) =>
    api.get<DocumentPage>(`/projects/${projectId}/reader/${docId}/pages/${pageNumber}`),
  pageSummary: (projectId: string, docId: string) =>
    api.get<Record<string, number>>(`/projects/${projectId}/reader/${docId}/page-summary`),
  referencingShots: (projectId: string, docId: string) =>
    api.get<any[]>(`/projects/${projectId}/reader/${docId}/referencing-shots`),
}

// ---------- 工程参数台账 ----------
export const factApi = {
  list: (projectId: string, params?: { status?: string; fact_type?: string; unverified_only?: boolean }) =>
    api.get<ExtractedFact[]>(`/projects/${projectId}/facts`, { params }),
  conflicts: (projectId: string) =>
    api.get<ExtractedFact[]>(`/projects/${projectId}/facts/conflicts`),
  types: () => api.get<Record<string, string>>('/facts/types').catch(() => ({ data: {} })),
  confirm: (projectId: string, factId: string, payload: { status: string; fact_value?: string; unit?: string; note?: string }) =>
    api.post<{ id: string; status: string; message: string }>(`/projects/${projectId}/facts/${factId}/confirm`, payload),
}

// ---------- 评分点 ----------
export const scoringApi = {
  list: (projectId: string) => api.get<ScoringPoint[]>(`/projects/${projectId}/scoring`),
  coverage: (projectId: string) =>
    api.get<ScoringCoverage>(`/projects/${projectId}/scoring/coverage`),
}

// ---------- 分镜 ----------
export const storyboardApi = {
  list: (projectId: string) =>
    api.get<StoryboardShot[]>(`/projects/${projectId}/storyboard`),
  summary: (projectId: string) =>
    api.get<StoryboardSummary>(`/projects/${projectId}/storyboard/summary`),
  create: (projectId: string, payload: Partial<StoryboardShot>) =>
    api.post<StoryboardShot>(`/projects/${projectId}/storyboard`, {
      project_id: projectId,
      ...payload,
    }),
  generate: (
    projectId: string,
    payload: {
      section_count: number
      tone: string
      target_duration_seconds?: number
      video_purpose?: string
      focus_scoring_points?: string[]
      include_company_intro?: boolean
      include_construction_simulation?: boolean
    },
  ) =>
    api.post<{ task_id: string }>(`/projects/${projectId}/storyboard/generate`, {
      project_id: projectId,
      ...payload,
    }),
  update: (projectId: string, shotId: string, payload: Partial<StoryboardShot>) =>
    api.patch<StoryboardShot>(`/projects/${projectId}/storyboard/${shotId}`, payload),
  restore: (projectId: string, shotId: string, revision: number) =>
    api.post<StoryboardShot>(`/projects/${projectId}/storyboard/${shotId}/restore`, { revision }),
  reorder: (projectId: string, shotIds: string[]) =>
    api.post<StoryboardShot[]>(`/projects/${projectId}/storyboard/reorder`, { shot_ids: shotIds }),
  regenerate: (projectId: string, shotId: string, hint?: string) =>
    api.post<{ task_id: string }>(`/projects/${projectId}/storyboard/${shotId}/regenerate`, {
      shot_id: shotId,
      prompt_hint: hint,
    }),
  remove: (projectId: string, shotId: string) =>
    api.delete(`/projects/${projectId}/storyboard/${shotId}`),
}

// ---------- 素材 ----------
export const assetApi = {
  list: (projectId: string, assetType?: string) =>
    api.get<Asset[]>(`/projects/${projectId}/assets`, { params: { asset_type: assetType } }),
  upload: (projectId: string, file: File, name?: string) => {
    const form = new FormData()
    form.append('file', file)
    if (name) form.append('name', name)
    return api.post<Asset>(`/projects/${projectId}/assets`, form)
  },
  aiImage: (projectId: string, shotId: string, prompt?: string) => {
    const form = new FormData()
    form.append('shot_id', shotId)
    if (prompt) form.append('prompt', prompt)
    return api.post<{ task_id: string }>(`/projects/${projectId}/assets/ai-image`, form)
  },
  aiTts: (projectId: string, shotId: string, voiceName: string, speed: number) => {
    const form = new FormData()
    form.append('shot_id', shotId)
    form.append('voice_name', voiceName)
    form.append('speed', String(speed))
    return api.post<{ task_id: string }>(`/projects/${projectId}/assets/ai-tts`, form)
  },
  aiVideo: (projectId: string, shotId: string, prompt?: string, duration = 5) => {
    const form = new FormData()
    form.append('shot_id', shotId)
    if (prompt) form.append('prompt', prompt)
    form.append('duration', String(duration))
    return api.post<{ task_id: string }>(`/projects/${projectId}/assets/ai-video`, form)
  },
  remove: (projectId: string, assetId: string) =>
    api.delete(`/projects/${projectId}/assets/${assetId}`),
}

// ---------- 任务 ----------
export const taskApi = {
  list: (params?: { project_id?: string; status?: string }) =>
    api.get<RenderTask[]>('/tasks', { params }),
  detail: (id: string) => api.get<RenderTask>(`/tasks/${id}`),
  retry: (id: string) => api.post<RenderTask>(`/tasks/${id}/retry`, {}),
  cancel: (id: string) => api.post<RenderTask>(`/tasks/${id}/cancel`, {}),
}

// ---------- 配音模板 ----------
export const voiceApi = {
  list: (projectId: string) => api.get<VoiceTemplate[]>(`/projects/${projectId}/voices`),
  create: (projectId: string, payload: Partial<VoiceTemplate>) =>
    api.post<VoiceTemplate>(`/projects/${projectId}/voices`, payload),
  remove: (projectId: string, voiceId: string) =>
    api.delete(`/projects/${projectId}/voices/${voiceId}`),

  // Phase 4：估算 / 生成 / 批量 / 任务
  estimate: (projectId: string, shotId: string, voiceTemplateId?: string) =>
    api.post<VoiceEstimate>(`/projects/${projectId}/voice/estimate`, {
      shot_id: shotId,
      voice_template_id: voiceTemplateId,
    }),
  generate: (projectId: string, payload: Record<string, any>) =>
    api.post<{ task_id: string; status: string }>(`/projects/${projectId}/voice/generate`, payload),
  batch: (projectId: string, payload: Record<string, any>) =>
    api.post<{ task_id: string; status: string; total: number }>(`/projects/${projectId}/voice/batch`, payload),
  jobs: (projectId: string, params?: { status?: string; shot_id?: string }) =>
    api.get<VoiceJob[]>(`/projects/${projectId}/voice/jobs`, { params }),
  jobDetail: (projectId: string, jobId: string) =>
    api.get<VoiceJob>(`/projects/${projectId}/voice/jobs/${jobId}`),
  retryJob: (projectId: string, jobId: string) =>
    api.post<VoiceJob>(`/projects/${projectId}/voice/jobs/${jobId}/retry`),
  cancelJob: (projectId: string, jobId: string) =>
    api.post<VoiceJob>(`/projects/${projectId}/voice/jobs/${jobId}/cancel`),

  // Phase 4：版本管理
  versions: (projectId: string, shotId: string) =>
    api.get<AudioVersion[]>(`/projects/${projectId}/storyboard/${shotId}/voice/versions`),
  selectVersion: (projectId: string, shotId: string, versionId: string) =>
    api.post(`/projects/${projectId}/storyboard/${shotId}/voice/versions/${versionId}/select`),
  restoreVersion: (projectId: string, shotId: string, versionId: string) =>
    api.post(`/projects/${projectId}/storyboard/${shotId}/voice/restore`, { version_id: versionId }),
  deleteVersion: (projectId: string, shotId: string, versionId: string) =>
    api.delete(`/projects/${projectId}/storyboard/${shotId}/voice/versions/${versionId}`),

  // Phase 4：字幕
  subtitles: (projectId: string, shotId: string, versionId?: string) =>
    api.get<{ shot_id: string; version_id: string; version_number: number; subtitle_data: SubtitleSegment[]; audio_url?: string; duration_seconds?: number }>(
      `/projects/${projectId}/storyboard/${shotId}/subtitles`,
      { params: versionId ? { version_id: versionId } : {} },
    ),
  updateSubtitles: (projectId: string, shotId: string, segments: { sequence: number; start_ms: number; end_ms: number }[]) =>
    api.patch(`/projects/${projectId}/storyboard/${shotId}/subtitles`, { segments }),

  // Phase 4：导出 / 汇总
  summary: (projectId: string) => api.get<VoiceSummary>(`/projects/${projectId}/voice/summary`),
}

// ---------- 全局配音 Provider / 模板 ----------
export const voiceProviderApi = {
  list: () => api.get<any[]>('/voice/providers'),
  capabilities: (provider: string) =>
    api.get<Record<string, boolean>>(`/voice/providers/${provider}/capabilities`),
  voices: (provider: string) => api.get<any[]>(`/voice/providers/${provider}/voices`),
  speakingStyles: () => api.get<string[]>('/voice/speaking-styles'),
}

export const voiceTemplateApi = {
  list: () => api.get<VoiceTemplate[]>('/voice/templates'),
  get: (id: string) => api.get<VoiceTemplate>(`/voice/templates/${id}`),
  create: (payload: Partial<VoiceTemplate>) => api.post<VoiceTemplate>('/voice/templates', payload),
  update: (id: string, payload: Partial<VoiceTemplate>) =>
    api.patch<VoiceTemplate>(`/voice/templates/${id}`, payload),
  remove: (id: string) => api.delete(`/voice/templates/${id}`),
  duplicate: (id: string) => api.post<VoiceTemplate>(`/voice/templates/${id}/duplicate`),
  preview: (id: string) =>
    api.post<{ asset_id: string; url: string; is_mock: boolean }>(`/voice/templates/${id}/preview`),
}

// ---------- 发音词典 ----------
export const pronunciationApi = {
  list: (projectId: string) => api.get<PronunciationRule[]>(`/projects/${projectId}/pronunciations`),
  create: (projectId: string, payload: Partial<PronunciationRule>) =>
    api.post<PronunciationRule>(`/projects/${projectId}/pronunciations`, payload),
  update: (projectId: string, ruleId: string, payload: Partial<PronunciationRule>) =>
    api.patch<PronunciationRule>(`/projects/${projectId}/pronunciations/${ruleId}`, payload),
  remove: (projectId: string, ruleId: string) =>
    api.delete(`/projects/${projectId}/pronunciations/${ruleId}`),
  test: (projectId: string, text: string) =>
    api.post<{ original_text: string; normalized_text: string; pronunciation_snapshot: any[]; matched_rules: any[]; warnings: string[] }>(
      `/projects/${projectId}/pronunciations/test`,
      { text },
    ),
  importJson: (projectId: string, rules: any[]) =>
    api.post(`/projects/${projectId}/pronunciations/import`, { rules }),
  exportJson: (projectId: string) => api.get(`/projects/${projectId}/pronunciations/export`),
}

// ---------- 配音文件下载（带认证） ----------
export async function downloadVoiceFile(projectId: string, kind: 'wav' | 'mp3' | 'srt', shotId?: string) {
  const token = localStorage.getItem('fastvideo_token')
  let url = `/api/v1/projects/${projectId}/voice/export/${kind}`
  let filename = `项目配音_${kind}.${kind === 'srt' ? 'srt' : 'zip'}`
  if (shotId) {
    url = `/api/v1/projects/${projectId}/storyboard/${shotId}/subtitles/export`
    filename = `shot_${shotId.slice(0, 8)}.srt`
  }
  const resp = await fetch(url, { headers: token ? { Authorization: `Bearer ${token}` } : {} })
  if (!resp.ok) throw new Error('下载失败')
  const blob = await resp.blob()
  const link = document.createElement('a')
  link.href = URL.createObjectURL(blob)
  link.download = filename
  link.click()
  URL.revokeObjectURL(link.href)
}

// ---------- 视频工程与导出 ----------
export const videoApi = {
  list: (projectId: string) => api.get<VideoProject[]>(`/projects/${projectId}/video-projects`),
  create: (projectId: string, payload: Record<string, any>) =>
    api.post<VideoProject>(`/projects/${projectId}/video-projects`, {
      project_id: projectId,
      ...payload,
    }),
  detail: (id: string) => api.get<VideoProject>(`/video-projects/${id}`),
  update: (id: string, payload: Partial<VideoProject>) =>
    api.patch<VideoProject>(`/video-projects/${id}`, payload),
  remove: (id: string) => api.delete(`/video-projects/${id}`),
  // 旧导出（兼容）
  export: (id: string) =>
    api.post<{ export_task_id: string; render_task_id: string; status: string }>(
      `/video-projects/${id}/export`,
      { video_project_id: id, export_format: 'mp4' },
    ),

  // Phase 5：分段
  syncStoryboard: (id: string) => api.post(`/video-projects/${id}/sync-storyboard`),
  segments: (id: string) => api.get<VideoSegment[]>(`/video-projects/${id}/segments`),
  updateSegment: (id: string, segId: string, payload: Record<string, any>) =>
    api.patch<VideoSegment>(`/video-projects/${id}/segments/${segId}`, payload),
  reorderSegments: (id: string, segmentIds: string[]) =>
    api.post<VideoSegment[]>(`/video-projects/${id}/segments/reorder`, { segment_ids: segmentIds }),
  renderSegment: (id: string, segId: string) =>
    api.post(`/video-projects/${id}/segments/${segId}/render`),
  previewSegment: (id: string, segId: string) =>
    api.post(`/video-projects/${id}/segments/${segId}/preview`),
  retrySegment: (id: string, segId: string) =>
    api.post(`/video-projects/${id}/segments/${segId}/retry`),
  renderAllSegments: (id: string) =>
    api.post(`/video-projects/${id}/segments/render-all`),

  // Phase 5：预检 / 导出
  preflight: (id: string, mode: 'demo' | 'formal') =>
    api.post<PreflightResult>(`/video-projects/${id}/preflight`, null, { params: { mode } }),
  exportDemo: (id: string) =>
    api.post<{ export_task_id: string; status: string; mode: string }>(`/video-projects/${id}/export/demo`),
  exportFormal: (id: string) =>
    api.post<{ export_task_id: string; status: string; mode: string }>(`/video-projects/${id}/export/formal`),
  vpExports: (id: string) => api.get<ExportTask[]>(`/video-projects/${id}/exports`),
}

export const exportApi = {
  list: (projectId?: string) => api.get<ExportTask[]>('/exports', { params: { project_id: projectId } }),
  detail: (id: string) => api.get<ExportTask>(`/exports/${id}`),
  cancel: (id: string) => api.post<ExportTask>(`/exports/${id}/cancel`),
  retry: (id: string) => api.post<ExportTask>(`/exports/${id}/retry`),
}

// ---------- 视频文件下载（带认证） ----------
export async function downloadVideoFile(kind: 'mp4' | 'srt' | 'report', exportId: string) {
  const token = localStorage.getItem('fastvideo_token')
  const url = `/api/v1/exports/${exportId}/${kind === 'mp4' ? 'download' : kind}`
  const resp = await fetch(url, { headers: token ? { Authorization: `Bearer ${token}` } : {} })
  if (!resp.ok) throw new Error('下载失败')
  const blob = await resp.blob()
  const link = document.createElement('a')
  link.href = URL.createObjectURL(blob)
  link.download = `export_${exportId.slice(0, 8)}.${kind === 'report' ? 'json' : kind}`
  link.click()
  URL.revokeObjectURL(link.href)
}

// ---------- 渲染预设 ----------
export const renderPresetApi = {
  list: () => api.get<RenderPreset[]>('/render-presets'),
  create: (payload: Partial<RenderPreset>) => api.post<RenderPreset>('/render-presets', payload),
  update: (id: string, payload: Partial<RenderPreset>) =>
    api.patch<RenderPreset>(`/render-presets/${id}`, payload),
  duplicate: (id: string) =>
    api.post<RenderPreset>(`/render-presets/${id}/duplicate`),
}

// ---------- 画面渲染 ----------
export const renderApi = {
  enums: () => api.get<{ source_softwares: string[]; camera_angles: string[] }>('/render/enums'),
  providers: (projectId: string) =>
    api.get<any[]>(`/projects/${projectId}/render/providers`),
  providerCapabilities: (projectId: string, provider: string) =>
    api.get<Record<string, boolean>>(`/projects/${projectId}/render/providers/${provider}/capabilities`),
  uploadSourceImage: (
    projectId: string,
    file: File,
    meta: { name: string; source_software?: string; camera_angle?: string; storyboard_shot_id?: string },
  ) => {
    const form = new FormData()
    form.append('file', file)
    form.append('name', meta.name)
    form.append('source_software', meta.source_software || 'Revit')
    form.append('camera_angle', meta.camera_angle || '建筑人视')
    if (meta.storyboard_shot_id) form.append('storyboard_shot_id', meta.storyboard_shot_id)
    return api.post<SourceImage>(`/projects/${projectId}/render/source-images`, form)
  },
  listSourceImages: (projectId: string) =>
    api.get<SourceImage[]>(`/projects/${projectId}/render/source-images`),
  createTask: (projectId: string, payload: Record<string, any>) =>
    api.post<RenderJobTask>(`/projects/${projectId}/render/tasks`, payload),
  listTasks: (projectId: string, params?: { status?: string; shot_id?: string }) =>
    api.get<RenderJobTask[]>(`/projects/${projectId}/render/tasks`, { params }),
  getTask: (projectId: string, taskId: string) =>
    api.get<RenderJobTask>(`/projects/${projectId}/render/tasks/${taskId}`),
  retryTask: (projectId: string, taskId: string) =>
    api.post<RenderJobTask>(`/projects/${projectId}/render/tasks/${taskId}/retry`),
  cancelTask: (projectId: string, taskId: string) =>
    api.post<RenderJobTask>(`/projects/${projectId}/render/tasks/${taskId}/cancel`),
  taskResults: (projectId: string, taskId: string) =>
    api.get<RenderVersion[]>(`/projects/${projectId}/render/tasks/${taskId}/results`),
  listVersions: (projectId: string, params?: { source_asset_id?: string; shot_id?: string }) =>
    api.get<RenderVersion[]>(`/projects/${projectId}/render/versions`, { params }),
  getVersion: (projectId: string, versionId: string) =>
    api.get<RenderVersion>(`/projects/${projectId}/render/versions/${versionId}`),
  deleteVersion: (projectId: string, versionId: string) =>
    api.delete(`/projects/${projectId}/render/versions/${versionId}`),
  uploadMask: (projectId: string, file: File) => {
    const form = new FormData()
    form.append('file', file)
    return api.post<{ asset_id: string; width: number; height: number; file_key: string }>(
      `/projects/${projectId}/render/mask`,
      form,
    )
  },
  inpaint: (projectId: string, payload: Record<string, any>) =>
    api.post<RenderJobTask>(`/projects/${projectId}/render/inpaint`, payload),
  outpaint: (projectId: string, payload: Record<string, any>) =>
    api.post<RenderJobTask>(`/projects/${projectId}/render/outpaint`, payload),
  upscale: (projectId: string, payload: Record<string, any>) =>
    api.post<RenderJobTask>(`/projects/${projectId}/render/upscale`, payload),
}

// ---------- 分镜画面绑定 ----------
export const shotVisualApi = {
  select: (projectId: string, shotId: string, versionId: string) =>
    api.post<Record<string, any>>(`/projects/${projectId}/storyboard/${shotId}/visual/select`, {
      version_id: versionId,
    }),
  history: (projectId: string, shotId: string) =>
    api.get<Record<string, any>>(`/projects/${projectId}/storyboard/${shotId}/visual/history`),
  restore: (projectId: string, shotId: string, versionId: string) =>
    api.post<Record<string, any>>(`/projects/${projectId}/storyboard/${shotId}/visual/restore`, {
      version_id: versionId,
    }),
}

// ---------- AI 视频生成（Phase 7：Seedance 图片驱动视频分镜） ----------
export const videoGenApi = {
  // 模板
  templates: (projectId: string, mode?: string) =>
    api.get<VideoGenerationTemplate[]>(`/projects/${projectId}/ai-video/templates`, {
      params: mode ? { mode } : {},
    }),
  createTemplate: (projectId: string, payload: Partial<VideoGenerationTemplate>) =>
    api.post<VideoGenerationTemplate>(`/projects/${projectId}/ai-video/templates`, payload),
  updateTemplate: (projectId: string, templateId: string, payload: Partial<VideoGenerationTemplate>) =>
    api.patch<VideoGenerationTemplate>(`/projects/${projectId}/ai-video/templates/${templateId}`, payload),
  deleteTemplate: (projectId: string, templateId: string) =>
    api.delete(`/projects/${projectId}/ai-video/templates/${templateId}`),

  // Provider / 参考帧 / 约束
  providers: (projectId: string) =>
    api.get<any[]>(`/projects/${projectId}/ai-video/providers`),
  providerCapabilities: (projectId: string, provider: string) =>
    api.get<Record<string, boolean>>(`/projects/${projectId}/ai-video/providers/${provider}/capabilities`),
  referenceImages: (projectId: string) =>
    api.get<ReferenceImage[]>(`/projects/${projectId}/ai-video/reference-images`),
  constraintCheck: (projectId: string, text: string) =>
    api.post<{ conflicts: string[]; blocked: boolean }>(
      `/projects/${projectId}/ai-video/constraint-check`,
      { text },
    ),

  // 提示词大师：读参考帧生成视频提示词
  promptMaster: (
    projectId: string,
    payload: {
      first_frame_asset_id?: string | null
      last_frame_asset_id?: string | null
      reference_asset_ids?: string[]
      template_id?: string | null
      intent?: string | null
      generation_mode: 'image_to_video' | 'first_last_frame_video'
    },
  ) =>
    api.post<{ prompt: string; negative_prompt?: string; mode: string; is_mock: boolean }>(
      `/projects/${projectId}/ai-video/prompt-master`,
      payload,
    ),

  // 任务
  createTask: (projectId: string, payload: Record<string, any>) =>
    api.post<VideoGenerationJob>(`/projects/${projectId}/ai-video/tasks`, payload),
  listTasks: (projectId: string, params?: { status?: string; shot_id?: string }) =>
    api.get<VideoGenerationJob[]>(`/projects/${projectId}/ai-video/tasks`, { params }),
  getTask: (projectId: string, jobId: string) =>
    api.get<VideoGenerationJob>(`/projects/${projectId}/ai-video/tasks/${jobId}`),
  retryTask: (projectId: string, jobId: string) =>
    api.post<VideoGenerationJob>(`/projects/${projectId}/ai-video/tasks/${jobId}/retry`),
  cancelTask: (projectId: string, jobId: string) =>
    api.post<VideoGenerationJob>(`/projects/${projectId}/ai-video/tasks/${jobId}/cancel`),

  // 版本
  taskVersions: (projectId: string, jobId: string) =>
    api.get<VideoGenerationVersion[]>(`/projects/${projectId}/ai-video/tasks/${jobId}/versions`),
  versions: (projectId: string, params?: { shot_id?: string }) =>
    api.get<VideoGenerationVersion[]>(`/projects/${projectId}/ai-video/versions`, { params }),
  selectVersion: (projectId: string, versionId: string) =>
    api.post<VideoGenerationVersion>(`/projects/${projectId}/ai-video/versions/${versionId}/select`, {}),
  bindVersion: (projectId: string, versionId: string, shotId: string) =>
    api.post<Record<string, any>>(`/projects/${projectId}/ai-video/versions/${versionId}/bind`, {
      shot_id: shotId,
    }),
  deleteVersion: (projectId: string, versionId: string) =>
    api.delete(`/projects/${projectId}/ai-video/versions/${versionId}`),
}

// AI 视频下载（文件服务挂载在 /files，无需 /api/v1 前缀）
export async function downloadAiVideo(resultUrl: string) {
  const token = localStorage.getItem('fastvideo_token')
  const resp = await fetch(resultUrl, { headers: token ? { Authorization: `Bearer ${token}` } : {} })
  if (!resp.ok) throw new Error('下载失败')
  const blob = await resp.blob()
  const link = document.createElement('a')
  link.href = URL.createObjectURL(blob)
  link.download = `ai_video_${Date.now()}.mp4`
  link.click()
  URL.revokeObjectURL(link.href)
}
