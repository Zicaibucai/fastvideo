// 与后端 Schema 对齐的类型定义

/** 后端任务状态的稳定边界；未知状态保留给向后兼容的 API 扩展。 */
export type TaskStatus =
  | 'pending'
  | 'queued'
  | 'running'
  | 'retrying'
  | 'success'
  | 'completed'
  | 'failed'
  | 'cancelled'
  | (string & {})

export interface User {
  id: string
  email: string
  username: string
  full_name?: string
  company?: string
  is_active: boolean
  is_superuser: boolean
  created_at: string
  updated_at: string
}

export interface Project {
  id: string
  name: string
  code?: string
  description?: string
  status: string
  last_entered_at?: string
  bid_area?: number
  area_source_page?: number
  bid_deadline?: string
  construction_period?: string
  bidder_name?: string
  doc_count: number
  shot_count: number
  asset_count: number
  created_at: string
  updated_at: string
}

export interface SourceDocument {
  id: string
  project_id: string
  file_name: string
  file_key: string
  file_type: string
  file_size: number
  page_count?: number
  title?: string
  doc_type: string
  parse_status: string
  parse_error?: string
  extracted_params?: Record<string, any>
  sha256?: string
  mime_type?: string
  is_duplicate?: boolean
  original_document_id?: string
  total_pages?: number
  ocr_pages?: number
  failed_pages?: number
  table_count?: number
  created_at: string
}

export interface ResumableUpload {
  id: string
  file_name: string
  file_size: number
  chunk_size: number
  total_chunks: number
  uploaded_chunks: number[]
  uploaded_bytes: number
  progress: number
  status: string
  document_id?: string
  error_message?: string
}

export interface DocumentPage {
  id: string
  document_id: string
  page_number: number
  location_label?: string
  raw_text?: string
  cleaned_text?: string
  markdown_text?: string
  page_type: string
  extraction_method: string
  ocr_status: string
  confidence?: number
  metadata_json?: Record<string, any>
  created_at: string
}

export interface DocumentChunk {
  id: string
  document_id: string
  sequence: number
  page_start?: number
  page_end?: number
  heading_path?: string
  content?: string
  token_count: number
  chunk_type: string
  created_at: string
}

export interface TocItem {
  heading_path: string
  heading_text: string
  level: number
  page?: number
  page_start?: number
  page_end?: number
}

export interface SearchResult {
  chunk_id: string
  document_id: string
  document_name: string
  page?: number
  location_label?: string
  heading_path?: string
  content: string
  highlight?: string
}

export interface ExtractedFact {
  id: string
  project_id: string
  document_id?: string
  document_name?: string
  page_number?: number
  source_order?: number
  location_label?: string
  fact_type: string
  fact_name: string
  fact_label: string
  fact_value: string
  scope?: string
  category?: string
  usage_status?: 'confirmed' | 'auto_usable' | 'review' | 'low_confidence' | 'conflict' | 'rejected'
  unit?: string
  source_quote?: string
  confidence: number
  verification_status: string
  confirmed_by?: string
  confirmed_at?: string
  candidates?: any[]
  created_at: string
}

export interface ScoringPoint {
  id: string
  project_id: string
  title: string
  description?: string
  score?: number
  score_total?: number
  source_document_id?: string
  source_page?: number
  source_quote?: string
  matched_shot_ids?: string[]
  category?: string
  created_at: string
}

export interface ScoringCoverage {
  total: number
  covered: number
  coverage_rate: number
  points: ScoringPoint[]
}

export interface SourceReference {
  documentId: string
  documentName: string
  page?: number
  locationLabel?: string
  quote?: string
}

export interface StoryboardShot {
  id: string
  project_id: string
  sequence: number
  title?: string
  section?: string
  narration?: string
  duration_seconds?: number
  source_page?: number
  visual_prompt?: string
  visual_type?: string
  visual_description?: string
  image_prompt?: string
  video_prompt?: string
  keywords?: string[]
  source_references?: SourceReference[]
  scoring_point_ids?: string[]
  fact_check_status?: string
  video_asset_id?: string
  audio_asset_id?: string
  audio_duration_status?: string
  audio_quality_status?: string
  audio_is_stale?: boolean
  tts_voice_id?: string
  video_clip_key?: string
  status: string
  is_active?: boolean
  revision?: number
  versions?: ShotVersion[]
  created_at: string
}

export interface ShotVersion {
  revision: number
  narration: string
  visual_prompt?: string
  visual_type?: string
  created_at: string
  source: string
}

export interface StoryboardSummary {
  shot_count: number
  beat_count?: number
  total_duration_seconds: number
  total_narration_characters: number
  scoring_coverage_rate: number
  scoring_covered: number
  scoring_total: number
  unverified_shot_count: number
  fact_status_counts: Record<string, number>
}

export interface NarrationBeat {
  id: string
  project_id: string
  shot_id?: string
  sequence: number
  shot_sequence: number
  narration: string
  start_time: number
  end_time: number
  evidence_ids?: string[]
  source_references?: SourceReference[]
  fact_check_status: string
  status: string
}

export interface Asset {
  id: string
  project_id?: string
  name: string
  asset_type: string
  source: string
  file_key?: string
  thumbnail_key?: string
  url?: string
  file_size: number
  mime_type?: string
  width?: number
  height?: number
  duration_seconds?: number
  prompt?: string
  tags?: string[]
  meta?: Record<string, any>
  project_stage?: string
  created_at: string
}

export interface RenderTask {
  id: string
  project_id?: string
  shot_id?: string
  task_type: string
  params?: Record<string, any>
  status: TaskStatus
  progress: number
  attempts: number
  max_attempts: number
  message?: string
  error_message?: string
  result?: Record<string, any>
  created_at: string
  updated_at: string
}

export interface VoiceTemplate {
  id: string
  project_id?: string
  name: string
  description?: string
  voice_provider: string
  voice_name: string
  provider_voice_id?: string
  model_name?: string
  language: string
  gender: string
  gender_style: string
  age_style?: string
  speaking_style?: string
  style?: string
  speed: number
  pitch: number
  volume: number
  pause_strength: number
  emotion?: string
  sample_rate: number
  audio_format: string
  pronunciation_profile_id?: string
  authorization_type: string
  authorization_status: string
  authorization_note?: string
  authorization_expire_at?: string
  preview_asset_id?: string
  preview_text?: string
  is_default: boolean
  is_system: boolean
  is_enabled: boolean
  sort_order: number
  created_by?: string
  created_at: string
  updated_at: string
}

export interface PronunciationRule {
  id: string
  project_id?: string
  profile_id?: string
  source_text: string
  spoken_text: string
  language: string
  rule_type: string
  priority: number
  is_regex: boolean
  enabled: boolean
  scope: string
  created_by?: string
  conflict_hint?: string
  created_at: string
}

export interface SubtitleSegment {
  sequence: number
  start_ms: number
  end_ms: number
  text: string
  normalized_text?: string
  timing_source: string
  confidence?: number
}

export interface AudioVersion {
  id: string
  project_id: string
  storyboard_shot_id: string
  voice_template_id?: string
  version_number: number
  original_text_snapshot?: string
  normalized_text_snapshot?: string
  pronunciation_snapshot?: any
  narration_hash?: string
  provider: string
  model_name?: string
  voice_id?: string
  speed: number
  pitch: number
  volume: number
  emotion?: string
  pause_strength: number
  seed?: number
  target_duration_seconds?: number
  estimated_duration_seconds?: number
  actual_duration_seconds?: number
  duration_difference?: number
  duration_difference_ratio?: number
  duration_status: string
  audio_asset_id?: string
  wav_asset_id?: string
  mp3_asset_id?: string
  audio_url?: string
  wav_url?: string
  mp3_url?: string
  subtitle_data: SubtitleSegment[]
  waveform_data?: any
  provider_metadata?: any
  quality_metrics?: any
  quality_status: string
  authorization_snapshot?: any
  is_mock: boolean
  is_stale: boolean
  stale_reason?: string
  is_selected: boolean
  selected_by?: string
  selected_at?: string
  estimated_cost: number
  actual_cost: number
  currency: string
  created_at: string
  updated_at: string
}

export interface VoiceJob {
  id: string
  project_id?: string
  shot_id?: string
  parent_task_id?: string
  task_type: string
  status: TaskStatus
  progress: number
  params?: any
  result?: any
  error_message?: string
  message?: string
  children?: VoiceJob[]
  created_at: string
  updated_at: string
}

export interface VoiceEstimate {
  shot_id: string
  narration?: string
  normalized_text: string
  char_count: number
  effective_chars?: number
  target_duration_seconds: number
  estimated_duration_seconds: number
  duration_difference: number
  duration_difference_ratio: number
  suggestion: string
  recommended_speed_min: number
  recommended_speed_max: number
  warnings: string[]
}

export interface VoiceSummary {
  shot_count: number
  missing_voice_count: number
  stale_count: number
  mock_count: number
  total_actual_duration_seconds: number
  duration_status_counts: Record<string, number>
  quality_status_counts: Record<string, number>
}

export interface VideoProject {
  id: string
  project_id?: string
  name: string
  status: string
  width: number
  height: number
  fps: number
  duration_seconds?: number
  timeline?: TimelineItem[]
  subtitle_style?: any
  music_tracks?: any[]
  logo_config?: any
  open_config?: any
  close_config?: any
  brand_color: string
  export_mode: string
  timeline_snapshot?: any
  output_key?: string
  output_url?: string
  watermark_text?: string
  created_at: string
}

export interface VideoSegment {
  id: string
  video_project_id: string
  storyboard_shot_id?: string
  sequence: number
  visual_asset_id?: string
  audio_version_id?: string
  duration: number
  is_locked: boolean
  fit_mode: string
  time_adaptation?: string
  transition_type: string
  transition_duration: number
  subtitle_enabled: boolean
  volume: number
  render_status: string
  render_progress: number
  output_key?: string
  output_url?: string
  input_hash?: string
  needs_rebuild: boolean
  error_message?: string
  rendered_at?: string
  shot_title?: string
  narration?: string
  visual_url?: string
  visual_source_duration?: number
  visual_playback_speed?: number
  audio_url?: string
  has_visual: boolean
  has_audio: boolean
  has_subtitle: boolean
  visual_source?: string
  created_at: string
}

export interface PreflightIssue {
  level: 'error' | 'warning'
  code: string
  message: string
}

export interface PreflightResult {
  ok: boolean
  mode: string
  issues: PreflightIssue[]
  segment_count: number
  rendered_segment_count: number
  missing_render_count: number
}

export interface TimelineItem {
  shot_id: string
  sequence: number
  duration?: number
}

export interface ExportTask {
  id: string
  video_project_id?: string
  project_id?: string
  export_format: string
  mode: string
  status: string
  progress: number
  output_url?: string
  srt_url?: string
  report_url?: string
  file_size: number
  duration_seconds?: number
  error_message?: string
  timeline_snapshot?: any
  created_at: string
}

export interface AiStatus {
  llm: { provider: string; available: boolean; model: string }
  image: { provider: string; available: boolean; model: string }
  video: { provider: string; available: boolean; model: string }
  tts: { provider: string; available: boolean; model: string; voice: string }
  mock_mode: boolean
  tts_mock_mode?: boolean
}

export interface AIProviderSetting {
  provider: string
  label: string
  kind: string
  base_url: string
  model: string
  api_key_set: boolean
  api_key_hint: string
  api_key_warning?: string
  api_key?: string
}

export interface AIConfiguration {
  providers: AIProviderSetting[]
  stages: Record<string, { provider?: string; model?: string }>
  stage_options: Record<string, string>
}

export interface Page<T> {
  items: T[]
  total: number
  page: number
  page_size: number
  pages: number
}

// ---------- Phase 3 渲染 ----------
export interface RenderPreset {
  id: string
  name: string
  description?: string
  category?: string
  preview_image?: string
  default_positive_prompt?: string
  default_negative_prompt?: string
  recommended_aspect_ratio: string
  recommended_structure_strength: number
  is_system: boolean
  is_enabled: boolean
  created_by?: string
  sort_order: number
  created_at: string
}

export interface SourceImage {
  id: string
  project_id: string
  name: string
  asset_type: string
  source: string
  file_key?: string
  thumbnail_key?: string
  url?: string
  file_size: number
  width?: number
  height?: number
  aspect_ratio?: string
  color_mode?: string
  sha256?: string
  source_software?: string
  camera_angle?: string
  is_original_model_shot: boolean
  is_duplicate?: boolean
  duplicate_asset_id?: string
  created_at: string
}

export interface RenderJobTask {
  id: string
  project_id: string
  source_asset_id?: string
  preset_id?: string
  operation_type: string
  positive_prompt?: string
  negative_prompt?: string
  aspect_ratio: string
  output_width?: number
  output_height?: number
  variant_count: number
  structure_strength: number
  creativity: number
  seed?: number
  provider: string
  model_name?: string
  status: string
  progress: number
  error_message?: string
  estimated_cost: number
  actual_cost: number
  currency: string
  is_conceptual: boolean
  started_at?: string
  completed_at?: string
  created_at?: string
  version_count: number
}

export interface RenderVersion {
  id: string
  render_job_id?: string
  source_asset_id?: string
  result_asset_id?: string
  version_number: number
  provider: string
  model_name?: string
  seed?: number
  generation_type: string
  prompt_snapshot?: any
  negative_prompt_snapshot?: any
  parameter_snapshot?: any
  quality_metrics?: any
  quality_status: string
  is_selected: boolean
  selected_by?: string
  selected_at?: string
  is_deleted: boolean
  created_at: string
}

export interface QualityMetrics {
  quality_status: string
  structure_similarity_score: number
  edge_overlap_score: number
  change_ratio: number
  warnings: string[]
}

// ---------- Phase 7 AI 视频生成 ----------
export interface VideoGenerationTemplate {
  id: string
  name: string
  description?: string
  applicable_modes?: string[]
  default_positive_prompt?: string
  default_negative_prompt?: string
  recommended_duration: number
  recommended_aspect_ratio: string
  recommended_resolution: string
  recommended_camera_motion?: string
  default_arch_constraints?: string[]
  is_system: boolean
  is_enabled: boolean
  created_by?: string
  sort_order: number
  created_at: string
  category?: string
  tags?: string[]
  prompt_recipe?: Record<string, any>
  preview_asset_id?: string
  cover_asset_id?: string
  preview_file_key?: string
  cover_file_key?: string
  scope?: string
  status?: string
  source_video_asset_id?: string
  clip_start_seconds?: number
  clip_end_seconds?: number
  first_frame_asset_id?: string
  middle_frame_asset_id?: string
  last_frame_asset_id?: string
  first_frame_file_key?: string
  middle_frame_file_key?: string
  last_frame_file_key?: string
  reference_frame_asset_ids?: string[]
  reference_frame_times?: number[]
  reference_frame_count?: number
  source_license_confirmed?: boolean
}

export interface VideoGenerationJob {
  id: string
  project_id: string
  generation_mode: string
  first_frame_asset_id?: string
  last_frame_asset_id?: string
  reference_asset_ids?: string[]
  template_id?: string
  positive_prompt?: string
  negative_prompt?: string
  architecture_constraints?: string[]
  constraints_enabled: boolean
  provider: string
  model_name?: string
  duration: number
  aspect_ratio: string
  resolution: string
  seed?: number
  generate_audio: boolean
  watermark: boolean
  provider_task_id?: string
  status: TaskStatus
  progress: number
  error_message?: string
  elapsed_seconds?: number
  result_asset_id?: string
  asset_status?: 'processing' | 'ready' | 'failed'
  result_url?: string
  quality_report?: {
    fps?: number
    duration_seconds?: number
    warnings?: string[]
    engineering_review?: { status?: string; checks?: { name: string; status: string }[]; note?: string }
  }
  parameter_snapshot?: any
  created_by?: string
  started_at?: string
  completed_at?: string
  created_at?: string
  version_count: number
}

export interface VideoGenerationVersion {
  id: string
  video_job_id: string
  result_asset_id?: string
  name?: string
  result_url?: string
  version_number: number
  provider: string
  model_name?: string
  seed?: number
  generation_mode: string
  prompt_snapshot?: any
  negative_prompt_snapshot?: any
  parameter_snapshot?: any
  first_frame_asset_id?: string
  last_frame_asset_id?: string
  reference_asset_ids?: string[]
  quality_report?: {
    fps?: number
    duration_seconds?: number
    warnings?: string[]
    engineering_review?: { status?: string; checks?: { name: string; status: string }[]; note?: string }
  }
  template_id?: string
  is_selected: boolean
  selected_by?: string
  selected_at?: string
  is_deleted: boolean
  created_at?: string
}

export interface ReferenceImage {
  id: string
  name: string
  asset_type: string
  source: string
  file_key?: string
  thumbnail_key?: string
  url?: string
  file_size: number
  width?: number
  height?: number
  aspect_ratio?: string
  created_at?: string
}

export interface VideoTemplateDraft {
  id: string
  project_id: string
  source_video_asset_id: string
  source_video_name?: string
  source_video_file_key?: string
  source_video_duration_seconds?: number
  name: string
  description?: string
  status: string
  clip_start_seconds?: number
  clip_end_seconds?: number
  middle_seconds?: number
  first_frame_asset_id?: string
  middle_frame_asset_id?: string
  last_frame_asset_id?: string
  first_frame_file_key?: string
  middle_frame_file_key?: string
  last_frame_file_key?: string
  reference_frame_file_keys?: string[]
  reference_frame_asset_ids?: string[]
  reference_frame_times?: number[]
  prompt_recipe?: Record<string, any>
  analysis_warnings?: string[]
  intent?: string
  preview_job_id?: string
  preview_asset_id?: string
  preview_file_key?: string
  template_id?: string
  source_license_confirmed: boolean
  created_at: string
  updated_at: string
}
