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
  NarrationBeat,
  SubtitleSegment,
  TocItem,
  User,
  VideoGenerationJob,
  VideoGenerationTemplate,
  VideoGenerationVersion,
  VideoGenerationTaskCreate,
  VideoProvider,
  JsonObject,
  ReferenceImage,
  VideoProject,
  VideoSegment,
  VoiceEstimate,
  VoiceJob,
  VoiceSummary,
  VoiceTemplate,
  VoiceProviderInfo,
  VoiceDescriptor,
  RenderProviderInfo,
  ReferencingShot,
  PronunciationTestResult,
  PronunciationImportResult,
} from './types'

// ---------- 认证 ----------
export const authApi = {
  login: (email: string, password: string) =>
    api.post<{ access_token: string; token_type: string }>('/auth/login', { email, password }),
  logout: () => api.post('/auth/logout'),
  register: (payload: { email: string; username: string; password: string; company?: string }) =>
    api.post<User>('/auth/register', payload),
  me: () => api.get<User>('/auth/me'),
  updateMe: (payload: { username?: string; full_name?: string; company?: string; password?: string }) =>
    api.patch<User>('/auth/me', payload),
  aiConfiguration: () => api.get<import('./types').AIConfiguration>('/settings/ai'),
  saveAiConfiguration: (payload: { providers: JsonObject; stages: JsonObject }) =>
    api.put<import('./types').AIConfiguration>('/settings/ai', payload),
}

// ---------- Admin 人员系统 ----------
export const adminApi = {
  users: () => api.get<User[]>('/admin/users'),
  createUser: (payload: {
    email: string
    username: string
    password: string
    full_name?: string
    company?: string
    is_superuser?: boolean
  }) => api.post<User>('/admin/users', payload),
  updateUser: (
    id: string,
    payload: {
      username?: string
      full_name?: string | null
      company?: string | null
      password?: string
      is_active?: boolean
      is_superuser?: boolean
    },
  ) => api.patch<User>(`/admin/users/${id}`, payload),
}

// ---------- 系统 ----------
export const systemApi = {
  health: () => api.get('/health'),
  status: () => api.get<{ ai: AiStatus }>('/system/status'),
}

// ---------- 项目 ----------
export const projectApi = {
  list: (params?: {
    page?: number
    page_size?: number
    status?: string
    sort_by?: 'last_entered_at' | 'created_at' | 'name'
    sort_order?: 'asc' | 'desc'
  }) =>
    api.get<Page<Project>>('/projects', { params }),
  create: (payload: { name: string; code?: string; description?: string }) =>
    api.post<Project>('/projects', payload),
  detail: (id: string) => api.get<Project>(`/projects/${id}`),
  enter: (id: string) => api.post<Project>(`/projects/${id}/enter`),
  update: (id: string, payload: Record<string, unknown>) => api.patch<Project>(`/projects/${id}`, payload),
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
  uploadChunk: (projectId: string, uploadId: string, index: number, chunk: Blob, sha256?: string) =>
    api.put<ResumableUpload>(
      `/projects/${projectId}/documents/uploads/${uploadId}/chunks/${index}`,
      chunk,
      {
        headers: {
          'Content-Type': 'application/octet-stream',
          ...(sha256 ? { 'X-Chunk-SHA256': sha256 } : {}),
        },
        timeout: 180000,
      },
    ),
  completeResumableUpload: (projectId: string, uploadId: string) =>
    api.post<SourceDocument>(`/projects/${projectId}/documents/uploads/${uploadId}/complete`),
  cancelResumableUpload: (projectId: string, uploadId: string) =>
    api.delete(`/projects/${projectId}/documents/uploads/${uploadId}`),
  search: (projectId: string, q: string) =>
    api.get<SearchResult[]>(`/projects/${projectId}/documents/search`, { params: { q } }),
  reparse: (projectId: string, docId: string) =>
    api.post<SourceDocument>(`/projects/${projectId}/documents/${docId}/parse`),
  updateParams: (projectId: string, docId: string, params: JsonObject) =>
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
    api.get<ReferencingShot[]>(`/projects/${projectId}/reader/${docId}/referencing-shots`),
}

// ---------- 工程参数台账 ----------
export const factApi = {
  list: (projectId: string, params?: { status?: string; fact_type?: string; unverified_only?: boolean }) =>
    api.get<ExtractedFact[]>(`/projects/${projectId}/facts`, { params }),
  conflicts: (projectId: string) =>
    api.get<ExtractedFact[]>(`/projects/${projectId}/facts/conflicts`),
  types: (projectId: string) =>
    api.get<Record<string, string>>(`/projects/${projectId}/facts/types`).catch(() => ({ data: {} })),
  confirm: (projectId: string, factId: string, payload: { status: string; fact_value?: string; unit?: string; note?: string; base_revision?: number }) =>
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
  create: (projectId: string, payload: Partial<StoryboardShot> & { insert_at?: number }) =>
    api.post<StoryboardShot>(`/projects/${projectId}/storyboard`, {
      project_id: projectId,
      ...payload,
    }),
  generate: (
    projectId: string,
    payload: {
      section_count: number
      target_shot_count?: number
      tone: string
      target_duration_seconds?: number
      video_purpose?: string
      focus_scoring_points?: string[]
      include_company_intro?: boolean
      include_construction_simulation?: boolean
      chars_per_minute?: number
      generation_mode?: 'multi_stage' | 'single_pass'
      custom_requirements?: string
      predefined_outline?: string
      target_beat_count?: number
      evidence_batch_chars?: number
      evidence_concurrency?: number
      evidence_auto_approve?: boolean
      evidence_run_id?: string
      strict_fact_mode?: boolean
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
  beats: (projectId: string) =>
    api.get<NarrationBeat[]>(`/projects/${projectId}/storyboard/beats`),
  updateDocument: (projectId: string, shots: { shot_id: string; narration: string }[]) =>
    api.patch<{ updated_count: number; beat_count: number }>(`/projects/${projectId}/storyboard/document`, { shots }),
  resegment: (
    projectId: string,
    payload: { target_shot_count: number; chars_per_minute?: number; instructions?: string },
  ) => api.post<{ task_id: string; status: string }>(`/projects/${projectId}/storyboard/resegment`, payload),
  evidenceRun: (projectId: string, runId: string) =>
    api.get<JsonObject>(`/projects/${projectId}/storyboard/evidence/runs/${runId}`),
  approveEvidence: (projectId: string, runId: string, evidenceIds?: string[], continueGeneration = false) =>
    api.post<{ run_id: string; approved_count: number; status: string; task_id?: string }>(
      `/projects/${projectId}/storyboard/evidence/runs/${runId}/approve`,
      { ...(evidenceIds ? { evidence_ids: evidenceIds } : {}), continue_generation: continueGeneration },
    ),
}

// ---------- 素材 ----------
export const assetApi = {
  list: (projectId: string, assetType?: string, source?: string) =>
    api.get<Asset[]>(`/projects/${projectId}/assets`, { params: { asset_type: assetType, source } }),
  upload: (projectId: string, file: File, name?: string) => {
    const form = new FormData()
    form.append('file', file)
    if (name) form.append('name', name)
    return api.post<Asset>(`/projects/${projectId}/assets`, form)
  },
  update: (projectId: string, assetId: string, payload: { name?: string; tags?: string[]; meta?: JsonObject }) =>
    api.patch<Asset>(`/projects/${projectId}/assets/${assetId}`, payload),
  remove: (projectId: string, assetId: string) =>
    api.delete(`/projects/${projectId}/assets/${assetId}`),
}

// ---------- 任务 ----------
export const taskApi = {
  list: (params?: { project_id?: string; status?: string; task_type?: string }) =>
    api.get<RenderTask[]>('/tasks', { params }),
  detail: (id: string) => api.get<RenderTask>(`/tasks/${id}`),
  retry: (id: string) => api.post<RenderTask>(`/tasks/${id}/retry`, { task_id: id }),
  cancel: (id: string) => api.post<RenderTask>(`/tasks/${id}/cancel`, { task_id: id }),
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
  generate: (projectId: string, payload: JsonObject) =>
    api.post<{ task_id: string; status: string }>(`/projects/${projectId}/voice/generate`, payload),
  batch: (projectId: string, payload: JsonObject) =>
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
      // 分镜还没有正式配音版本是常态（尚未生成），不应每次选中都弹错误提示。
      { params: versionId ? { version_id: versionId } : {}, skipErrorToast: true },
    ),
  updateSubtitles: (projectId: string, shotId: string, segments: { sequence: number; start_ms: number; end_ms: number }[]) =>
    api.patch(`/projects/${projectId}/storyboard/${shotId}/subtitles`, { segments }),

  // Phase 4：导出 / 汇总
  summary: (projectId: string) => api.get<VoiceSummary>(`/projects/${projectId}/voice/summary`),
}

// ---------- 全局配音 Provider / 模板 ----------
export const voiceProviderApi = {
  list: () => api.get<VoiceProviderInfo[]>('/voice/providers'),
  capabilities: (provider: string) =>
    api.get<Record<string, boolean>>(`/voice/providers/${provider}/capabilities`),
  voices: (provider: string) => api.get<VoiceDescriptor[]>(`/voice/providers/${provider}/voices`),
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
    api.post<PronunciationTestResult>(
      `/projects/${projectId}/pronunciations/test`,
      { text },
    ),
  importJson: (projectId: string, rules: JsonObject[]) =>
    api.post<PronunciationImportResult>(`/projects/${projectId}/pronunciations/import`, { rules }),
  exportJson: (projectId: string) => api.get(`/projects/${projectId}/pronunciations/export`),
}

// ---------- 配音文件下载（带认证） ----------
export async function downloadVoiceFile(projectId: string, kind: 'wav' | 'mp3' | 'srt', shotId?: string) {
  let url = `/api/v1/projects/${projectId}/voice/export/${kind}`
  let filename = `项目配音_${kind}.${kind === 'srt' ? 'srt' : 'zip'}`
  if (shotId) {
    url = `/api/v1/projects/${projectId}/storyboard/${shotId}/subtitles/export`
    filename = `shot_${shotId.slice(0, 8)}.srt`
  }
  const resp = await fetch(url, { credentials: 'include' })
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
  create: (projectId: string, payload: JsonObject) =>
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
  updateSegment: (id: string, segId: string, payload: JsonObject) =>
    api.patch<VideoSegment>(`/video-projects/${id}/segments/${segId}`, payload),
  reorderSegments: (id: string, segmentIds: string[]) =>
    api.post<VideoSegment[]>(`/video-projects/${id}/segments/reorder`, { segment_ids: segmentIds }),
  renderSegment: (id: string, segId: string) =>
    api.post(`/video-projects/${id}/segments/${segId}/render`),
  previewSegment: (id: string, segId: string) =>
    api.post(`/video-projects/${id}/segments/${segId}/preview`),
  downloadSegment: (id: string, segId: string) =>
    `/api/v1/video-projects/${id}/segments/${segId}/download`,
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
  const url = `/api/v1/exports/${exportId}/${kind === 'mp4' ? 'download' : kind}`
  const resp = await fetch(url, { credentials: 'include' })
  if (!resp.ok) throw new Error('下载失败')
  const blob = await resp.blob()
  const link = document.createElement('a')
  link.href = URL.createObjectURL(blob)
  link.download = `export_${exportId.slice(0, 8)}.${kind === 'report' ? 'json' : kind}`
  link.click()
  URL.revokeObjectURL(link.href)
}

export async function downloadVideoSegment(videoProjectId: string, segmentId: string, sequence: number) {
  const url = videoApi.downloadSegment(videoProjectId, segmentId)
  const resp = await fetch(url, { credentials: 'include' })
  if (!resp.ok) throw new Error('下载分段失败')
  const blob = await resp.blob()
  const link = document.createElement('a')
  link.href = URL.createObjectURL(blob)
  link.download = `segment_${sequence}.mp4`
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
    api.get<RenderProviderInfo[]>(`/projects/${projectId}/render/providers`),
  providerCapabilities: (projectId: string, provider: string) =>
    api.get<Record<string, boolean>>(`/projects/${projectId}/render/providers/${provider}/capabilities`),
  uploadSourceImage: (
    projectId: string,
    file: File,
    meta: { name: string; source_software?: string; camera_angle?: string },
  ) => {
    const form = new FormData()
    form.append('file', file)
    form.append('name', meta.name)
    form.append('source_software', meta.source_software || 'Revit')
    form.append('camera_angle', meta.camera_angle || '建筑人视')
    return api.post<SourceImage>(`/projects/${projectId}/render/source-images`, form)
  },
  listSourceImages: (projectId: string) =>
    api.get<SourceImage[]>(`/projects/${projectId}/render/source-images`),
  createTask: (projectId: string, payload: JsonObject) =>
    api.post<RenderJobTask>(`/projects/${projectId}/render/tasks`, payload),
  listTasks: (projectId: string, params?: { status?: string }) =>
    api.get<RenderJobTask[]>(`/projects/${projectId}/render/tasks`, { params }),
  getTask: (projectId: string, taskId: string) =>
    api.get<RenderJobTask>(`/projects/${projectId}/render/tasks/${taskId}`),
  retryTask: (projectId: string, taskId: string) =>
    api.post<RenderJobTask>(`/projects/${projectId}/render/tasks/${taskId}/retry`),
  cancelTask: (projectId: string, taskId: string) =>
    api.post<RenderJobTask>(`/projects/${projectId}/render/tasks/${taskId}/cancel`),
  taskResults: (projectId: string, taskId: string) =>
    api.get<RenderVersion[]>(`/projects/${projectId}/render/tasks/${taskId}/results`),
  listVersions: (projectId: string, params?: { source_asset_id?: string }) =>
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
  inpaint: (projectId: string, payload: JsonObject) =>
    api.post<RenderJobTask>(`/projects/${projectId}/render/inpaint`, payload),
  outpaint: (projectId: string, payload: JsonObject) =>
    api.post<RenderJobTask>(`/projects/${projectId}/render/outpaint`, payload),
  upscale: (projectId: string, payload: JsonObject) =>
    api.post<RenderJobTask>(`/projects/${projectId}/render/upscale`, payload),
}

// ---------- AI 视频生成（Phase 7：Seedance 图片驱动视频素材） ----------
export const videoGenApi = {
  // 模板
  templates: (projectId: string, mode?: string, scope?: 'all' | 'personal' | 'organization') =>
    api.get<VideoGenerationTemplate[]>(`/projects/${projectId}/ai-video/templates`, {
      params: { ...(mode ? { mode } : {}), ...(scope ? { scope } : {}) },
    }),
  createTemplate: (projectId: string, payload: Partial<VideoGenerationTemplate>) =>
    api.post<VideoGenerationTemplate>(`/projects/${projectId}/ai-video/templates`, payload),
  updateTemplate: (projectId: string, templateId: string, payload: Partial<VideoGenerationTemplate>) =>
    api.patch<VideoGenerationTemplate>(`/projects/${projectId}/ai-video/templates/${templateId}`, payload),
  deleteTemplate: (projectId: string, templateId: string) =>
    api.delete(`/projects/${projectId}/ai-video/templates/${templateId}`),

  // Provider / 参考帧 / 约束
  providers: (projectId: string) =>
    api.get<VideoProvider[]>(`/projects/${projectId}/ai-video/providers`),
  providerCapabilities: (projectId: string, provider: string) =>
    api.get<Record<string, boolean>>(`/projects/${projectId}/ai-video/providers/${provider}/capabilities`),
  referenceImages: (projectId: string) =>
    api.get<ReferenceImage[]>(`/projects/${projectId}/ai-video/reference-images`),
  constraintCheck: (projectId: string, text: string, prompt_recipe?: JsonObject | null) =>
    api.post<{ conflicts: string[]; blocked: boolean }>(
      `/projects/${projectId}/ai-video/constraint-check`,
      { text, prompt_recipe: prompt_recipe || undefined },
    ),
  compilePrompt: (projectId: string, payload: {
    positive_prompt: string
    negative_prompt?: string | null
    prompt_recipe?: JsonObject | null
    template_id?: string | null
    constraints_enabled?: boolean
    resolution?: string | null
  }) =>
    api.post<{
      positive_prompt: string
      negative_prompt: string
      provider_prompt: string
      provider_prompt_chars: number
      provider_prompt_limit: number
      prompt_recipe?: JsonObject | null
      conflicts: string[]
      blocked: boolean
    }>(`/projects/${projectId}/ai-video/compile-prompt`, payload),

  // 提示词大师：读参考帧生成视频提示词
  promptMaster: (
    projectId: string,
    payload: {
      first_frame_asset_id?: string | null
      middle_frame_asset_id?: string | null
      last_frame_asset_id?: string | null
      reference_asset_ids?: string[]
      template_id?: string | null
      intent?: string | null
      generation_mode: 'image_to_video' | 'first_last_frame_video' | 'multi_reference_video'
    },
  ) =>
    api.post<{ prompt: string; name?: string; description?: string; negative_prompt?: string; mode: string; is_mock: boolean; provider?: string; model?: string; vision_used?: boolean; warnings?: string[]; recommended_duration?: number; recipe?: JsonObject }>(
      `/projects/${projectId}/ai-video/prompt-master`,
      payload,
    ),

  // 从专业视频创建可复用模板
  createTemplateDraft: (projectId: string, payload: {
    source_video_asset_id: string
    name: string
    description?: string
    /** 历史兼容字段，当前创建流程不再要求确认使用权。 */
    source_license_confirmed?: boolean
  }) => api.post<import('./types').VideoTemplateDraft>(`/projects/${projectId}/ai-video/template-drafts`, payload),
  listTemplateDrafts: (projectId: string) =>
    api.get<import('./types').VideoTemplateDraft[]>(`/projects/${projectId}/ai-video/template-drafts`),
  getTemplateDraft: (projectId: string, draftId: string) =>
    api.get<import('./types').VideoTemplateDraft>(`/projects/${projectId}/ai-video/template-drafts/${draftId}`),
  clipTemplateDraft: (projectId: string, draftId: string, payload: {
    clip_start_seconds: number
    clip_end_seconds: number
    middle_seconds?: number | number[]
  }) => api.post<import('./types').VideoTemplateDraft>(`/projects/${projectId}/ai-video/template-drafts/${draftId}/clip`, payload),
  analyzeTemplateDraft: (
    projectId: string,
    draftId: string,
    intent?: string,
    generationMode: 'image_to_video' | 'first_last_frame_video' | 'multi_reference_video' = 'image_to_video',
  ) =>
    api.post<import('./types').VideoTemplateDraft>(`/projects/${projectId}/ai-video/template-drafts/${draftId}/analyze`, {
      intent,
      generation_mode: generationMode,
    }),
  updateTemplateDraftRecipe: (projectId: string, draftId: string, payload: { name?: string; description?: string; prompt_recipe: JsonObject }) =>
    api.patch<import('./types').VideoTemplateDraft>(`/projects/${projectId}/ai-video/template-drafts/${draftId}/recipe`, payload),
  previewTemplateDraft: (projectId: string, draftId: string, payload?: { provider?: string; model_name?: string; duration?: number; aspect_ratio?: string; resolution?: string; structure_conflict_confirmed?: boolean }) =>
    api.post<VideoGenerationJob>(`/projects/${projectId}/ai-video/template-drafts/${draftId}/preview`, payload || {}),
  publishTemplateDraft: (projectId: string, draftId: string, payload: { name?: string; description?: string; category?: string; tags?: string[]; scope?: string }) =>
    api.post<VideoGenerationTemplate>(`/projects/${projectId}/ai-video/template-drafts/${draftId}/publish`, payload),

  // 任务
  createTask: (projectId: string, payload: VideoGenerationTaskCreate) =>
    api.post<VideoGenerationJob>(`/projects/${projectId}/ai-video/tasks`, payload),
  listTasks: (projectId: string, params?: { status?: string }) =>
    api.get<VideoGenerationJob[]>(`/projects/${projectId}/ai-video/tasks`, { params }),
  getTask: (projectId: string, jobId: string) =>
    api.get<VideoGenerationJob>(`/projects/${projectId}/ai-video/tasks/${jobId}`),
  retryTask: (projectId: string, jobId: string) =>
    api.post<VideoGenerationJob>(`/projects/${projectId}/ai-video/tasks/${jobId}/retry`),
  regenerateTask: (projectId: string, jobId: string) =>
    api.post<VideoGenerationJob>(`/projects/${projectId}/ai-video/tasks/${jobId}/regenerate`),
  cancelTask: (projectId: string, jobId: string) =>
    api.post<VideoGenerationJob>(`/projects/${projectId}/ai-video/tasks/${jobId}/cancel`),

  // 版本
  taskVersions: (projectId: string, jobId: string) =>
    api.get<VideoGenerationVersion[]>(`/projects/${projectId}/ai-video/tasks/${jobId}/versions`),
  versions: (projectId: string) =>
    api.get<VideoGenerationVersion[]>(`/projects/${projectId}/ai-video/versions`),
  renameVersion: (projectId: string, versionId: string, name: string) =>
    api.patch<VideoGenerationVersion>(`/projects/${projectId}/ai-video/versions/${versionId}`, { name }),
  selectVersion: (projectId: string, versionId: string) =>
    api.post<VideoGenerationVersion>(`/projects/${projectId}/ai-video/versions/${versionId}/select`, {}),
  deleteVersion: (projectId: string, versionId: string) =>
    api.delete(`/projects/${projectId}/ai-video/versions/${versionId}`),
}

// AI 视频下载（文件服务挂载在 /files，无需 /api/v1 前缀）
function safeDownloadName(name: string, fallback: string) {
  const clean = name.trim().replace(/[\\/:*?"<>|]+/g, '_')
  return clean || fallback
}

async function downloadProtectedFile(resultUrl: string, filename: string) {
  const resp = await fetch(resultUrl, { credentials: 'include' })
  if (!resp.ok) throw new Error('下载失败')
  const blob = await resp.blob()
  const link = document.createElement('a')
  link.href = URL.createObjectURL(blob)
  link.download = filename
  link.click()
  URL.revokeObjectURL(link.href)
}

export async function downloadAiVideo(resultUrl: string, filename?: string) {
  await downloadProtectedFile(
    resultUrl,
    safeDownloadName(filename || `ai_video_${Date.now()}.mp4`, `ai_video_${Date.now()}.mp4`),
  )
}

export async function downloadAssetFile(asset: Pick<Asset, 'file_key' | 'url' | 'name' | 'mime_type'>) {
  const resultUrl = asset.file_key ? `/files/${asset.file_key}` : asset.url || ''
  if (!resultUrl) throw new Error('素材没有可下载文件')
  const sourceKey = (asset.file_key || asset.url || '').split('?')[0]
  const extension = sourceKey.match(/\.[a-z0-9]{2,8}$/i)?.[0] || ''
  const baseName = safeDownloadName(asset.name, '素材')
  const filename = /\.[a-z0-9]{2,8}$/i.test(baseName) ? baseName : `${baseName}${extension}`
  await downloadProtectedFile(resultUrl, filename)
}

// ---------- 多人协作 ----------
import type {
  AppNotification,
  AuditLogEntry,
  CollabSummary,
  CollabTargetType,
  InvitationCreated,
  MyInvitation,
  ProjectComment,
  ProjectInvitation,
  ProjectMember,
  ProjectReviewStatus,
  ProjectRole,
  ProjectWorkItem,
  ReviewDetail,
  ReviewRequest,
  RolePermission,
} from './types'

export const collabApi = {
  roles: () => api.get<RolePermission[]>('/roles'),
  // 成员
  members: (projectId: string) => api.get<ProjectMember[]>(`/projects/${projectId}/members`),
  updateMemberRole: (projectId: string, memberId: string, role: ProjectRole) =>
    api.patch<ProjectMember>(`/projects/${projectId}/members/${memberId}`, { role }),
  removeMember: (projectId: string, memberId: string, reason?: string) =>
    api.delete(`/projects/${projectId}/members/${memberId}`, { data: { reason } }),
  leave: (projectId: string) => api.post(`/projects/${projectId}/members/leave`),
  transferOwnership: (projectId: string, newOwnerUserId: string, reason?: string) =>
    api.post(`/projects/${projectId}/transfer-ownership`, {
      new_owner_user_id: newOwnerUserId,
      reason,
    }),
  // 邀请
  invitations: (projectId: string) =>
    api.get<ProjectInvitation[]>(`/projects/${projectId}/invitations`),
  invite: (projectId: string, email: string, role: ProjectRole) =>
    api.post<InvitationCreated>(`/projects/${projectId}/invitations`, { email, role }),
  resendInvitation: (projectId: string, invitationId: string) =>
    api.post<InvitationCreated>(`/projects/${projectId}/invitations/${invitationId}/resend`),
  revokeInvitation: (projectId: string, invitationId: string) =>
    api.post<ProjectInvitation>(`/projects/${projectId}/invitations/${invitationId}/revoke`),
  myInvitations: () => api.get<MyInvitation[]>('/invitations/mine'),
  acceptInvitation: (token: string) =>
    api.post<ProjectMember>('/invitations/accept', { token }),
  // 评论
  comments: (projectId: string, params?: { target_type?: string; target_id?: string; status?: string }) =>
    api.get<ProjectComment[]>(`/projects/${projectId}/comments`, { params }),
  createComment: (
    projectId: string,
    payload: {
      target_type: CollabTargetType
      target_id?: string
      parent_id?: string
      body: string
      is_blocking?: boolean
    },
  ) => api.post<ProjectComment>(`/projects/${projectId}/comments`, payload),
  updateComment: (projectId: string, commentId: string, body: string) =>
    api.patch<ProjectComment>(`/projects/${projectId}/comments/${commentId}`, { body }),
  resolveComment: (projectId: string, commentId: string) =>
    api.post<ProjectComment>(`/projects/${projectId}/comments/${commentId}/resolve`),
  reopenComment: (projectId: string, commentId: string) =>
    api.post<ProjectComment>(`/projects/${projectId}/comments/${commentId}/reopen`),
  deleteComment: (projectId: string, commentId: string) =>
    api.delete(`/projects/${projectId}/comments/${commentId}`),
  // 待办
  workItems: (
    projectId: string,
    params?: { assignee_id?: string; status?: string; priority?: string; mine?: boolean },
  ) => api.get<ProjectWorkItem[]>(`/projects/${projectId}/work-items`, { params }),
  createWorkItem: (
    projectId: string,
    payload: {
      title: string
      description?: string
      target_type?: CollabTargetType
      target_id?: string
      assignee_id?: string
      comment_id?: string
      priority?: string
      due_at?: string
    },
  ) => api.post<ProjectWorkItem>(`/projects/${projectId}/work-items`, payload),
  updateWorkItem: (projectId: string, itemId: string, payload: Record<string, unknown>) =>
    api.patch<ProjectWorkItem>(`/projects/${projectId}/work-items/${itemId}`, payload),
  deleteWorkItem: (projectId: string, itemId: string) =>
    api.delete(`/projects/${projectId}/work-items/${itemId}`),
  // 审核
  reviewStatus: (projectId: string, videoProjectId?: string) =>
    api.get<ProjectReviewStatus>(`/projects/${projectId}/review-status`, {
      params: videoProjectId ? { video_project_id: videoProjectId } : {},
    }),
  reviews: (projectId: string, params?: { status?: string; target_type?: string; mine?: boolean }) =>
    api.get<ReviewRequest[]>(`/projects/${projectId}/reviews`, { params }),
  submitReview: (
    projectId: string,
    payload: {
      target_type: CollabTargetType
      target_id?: string
      note?: string
      assigned_reviewer_id?: string
    },
  ) => api.post<ReviewRequest>(`/projects/${projectId}/reviews`, payload),
  reviewDetail: (projectId: string, requestId: string) =>
    api.get<ReviewDetail>(`/projects/${projectId}/reviews/${requestId}`),
  decideReview: (
    projectId: string,
    requestId: string,
    payload: { decision: string; comment?: string; override_reason?: string },
  ) => api.post<ReviewRequest>(`/projects/${projectId}/reviews/${requestId}/decide`, payload),
  cancelReview: (projectId: string, requestId: string) =>
    api.post<ReviewRequest>(`/projects/${projectId}/reviews/${requestId}/cancel`),
  // 审计与总览
  auditLogs: (projectId: string, params?: { action?: string; limit?: number }) =>
    api.get<AuditLogEntry[]>(`/projects/${projectId}/audit-logs`, { params }),
  summary: (projectId: string) => api.get<CollabSummary>(`/projects/${projectId}/collaboration/summary`),
}

export const notificationApi = {
  list: (params?: { unread_only?: boolean; limit?: number }) =>
    api.get<AppNotification[]>('/notifications', { params }),
  unreadCount: () => api.get<{ count: number }>('/notifications/unread-count'),
  markRead: (id: string) => api.post<AppNotification>(`/notifications/${id}/read`),
  markAllRead: () => api.post('/notifications/read-all'),
}
