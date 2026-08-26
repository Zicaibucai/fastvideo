import { useCallback, useEffect, useRef, useState } from 'react'
import type { ColumnsType } from 'antd/es/table'
import {
  Card,
  Typography,
  Button,
  Space,
  Dropdown,
  Table,
  List,
  Tag,
  Modal,
  Form,
  Input,
  InputNumber,
  App,
  Tooltip,
  Empty,
  Select,
  Descriptions,
  Switch,
  Statistic,
  Row,
  Col,
  Segmented,
} from 'antd'
import {
  PlayCircleOutlined,
  ReloadOutlined,
  DeleteOutlined,
  HistoryOutlined,
  PictureOutlined,
  UpOutlined,
  DownOutlined,
  SettingOutlined,
  LinkOutlined,
  CopyOutlined,
  MoreOutlined,
  PlusOutlined,
  DownloadOutlined,
} from '@ant-design/icons'
import { useParams, useNavigate } from 'react-router-dom'
import { storyboardApi, scoringApi, taskApi } from '../api'
import type { StoryboardShot, StoryboardSummary, RenderTask, NarrationBeat } from '../api/types'
import { useTaskPolling } from '../components/TaskStatus'
import { useProjectNotifications } from '../components/ProjectNotificationCenter'

const { Title, Text, Paragraph } = Typography

const SECTION_OPTIONS = ['片头', '项目概况', '施工部署', '项目重难点', '施工方案', '保证措施', '片尾']
const VISUAL_TYPES = [
  { label: '标题', value: 'title' },
  { label: '模型图片', value: 'model_image' },
  { label: '现场照片', value: 'site_photo' },
  { label: 'AI生成图片', value: 'generated_image' },
  { label: 'AI生成视频', value: 'generated_video' },
  { label: 'BIM动画', value: 'bim_animation' },
  { label: '信息图表', value: 'infographic' },
]

const FACT_STATUS_MAP: Record<string, { label: string; color: string }> = {
  verified: { label: '已核实', color: 'success' },
  partial: { label: '部分核实', color: 'warning' },
  unverified: { label: '未验证', color: 'error' },
  conflict: { label: '冲突', color: 'volcano' },
}

type StoryboardViewMode = 'document' | 'preview' | 'storyboard'

function formatTimecode(seconds: number) {
  const safeSeconds = Math.max(0, Math.floor(seconds || 0))
  const minutes = Math.floor(safeSeconds / 60)
  const remaining = safeSeconds % 60
  return `${minutes}:${String(remaining).padStart(2, '0')}`
}

function splitPreviewParagraphs(text: string) {
  const sentences = (text || '')
    .split(/(?<=[。！？；])/)
    .map((sentence) => sentence.trim())
    .filter(Boolean)
  if (sentences.length === 0 && text.trim()) return [text.trim()]

  const paragraphs: string[] = []
  let current = ''
  for (const sentence of sentences) {
    const next = current ? `${current}${sentence}` : sentence
    if (current && next.length > 110) {
      paragraphs.push(current)
      current = sentence
    } else {
      current = next
    }
  }
  if (current) paragraphs.push(current)
  return paragraphs
}

export default function Storyboard() {
  const { projectId = '' } = useParams()
  const navigate = useNavigate()
  const { message } = App.useApp()
  const [shots, setShots] = useState<StoryboardShot[]>([])
  const [summary, setSummary] = useState<StoryboardSummary | null>(null)
  const [loading, setLoading] = useState(false)
  const [generating, setGenerating] = useState(false)
  const [genTaskId, setGenTaskId] = useState<string | null>(null)
  const [editShot, setEditShot] = useState<StoryboardShot | null>(null)
  const [editForm] = Form.useForm()
  const [addForm] = Form.useForm()
  const [genForm] = Form.useForm()
  const [genModalOpen, setGenModalOpen] = useState(false)
  const [historyShot, setHistoryShot] = useState<StoryboardShot | null>(null)
  const [addModalOpen, setAddModalOpen] = useState(false)
  const [scoringNames, setScoringNames] = useState<Record<string, string>>({})
  const [evidenceRunId, setEvidenceRunId] = useState<string | null>(null)
  const [evidenceRun, setEvidenceRun] = useState<Record<string, any> | null>(null)
  const [evidenceModalOpen, setEvidenceModalOpen] = useState(false)
  const [failedTask, setFailedTask] = useState<RenderTask | null>(null)
  const [viewMode, setViewMode] = useState<StoryboardViewMode>('document')
  const [showShotMarkers, setShowShotMarkers] = useState(true)
  const [showSubtitleBreaks, setShowSubtitleBreaks] = useState(false)
  const [showSourceMarkers, setShowSourceMarkers] = useState(false)
  const [beats, setBeats] = useState<NarrationBeat[]>([])
  const [documentDrafts, setDocumentDrafts] = useState<Record<string, string>>({})
  const [documentDirty, setDocumentDirty] = useState(false)
  const [savingDocument, setSavingDocument] = useState(false)
  const [resegmentModalOpen, setResegmentModalOpen] = useState(false)
  const [resegmentForm] = Form.useForm()
  const documentRefs = useRef<Record<string, HTMLDivElement | null>>({})
  const { upsertNotice, removeNotice } = useProjectNotifications()

  const fetchShots = () => {
    setLoading(true)
    Promise.all([
      storyboardApi.list(projectId),
      storyboardApi.summary(projectId),
      scoringApi.list(projectId),
    ])
      .then(([shotsRes, summaryRes, scoringRes]) => {
        setShots(shotsRes.data)
        setSummary(summaryRes.data)
        setDocumentDrafts(Object.fromEntries(shotsRes.data.map((shot) => [shot.id, shot.narration || ''])))
        setDocumentDirty(false)
        const names: Record<string, string> = {}
        scoringRes.data.forEach((s) => (names[s.id] = s.title))
        setScoringNames(names)
      })
      .finally(() => setLoading(false))
    storyboardApi.beats(projectId).then((res) => setBeats(res.data)).catch(() => setBeats([]))
  }

  useEffect(fetchShots, [projectId])

  useEffect(() => {
    taskApi.list({ project_id: projectId, task_type: 'gen_narration' }).then((res) => {
      const latest = res.data[0]
      if (!latest) return
      if (latest.status === 'failed') setFailedTask(latest)
      if (['queued', 'running', 'retry'].includes(latest.status)) {
        setGenTaskId(latest.id)
        setGenerating(true)
      }
    }).catch(() => {})
  }, [projectId])

  // 轮询生成任务
  const generationTask = useTaskPolling(genTaskId, (task) => {
    if (task.status === 'failed') {
      setFailedTask(task)
      setGenTaskId(null)
      setGenerating(false)
      message.error(task.error_message || '解说词生成中断，可继续处理')
      return
    }
    const runId = task.result?.stage_summary?.run_id
    if (runId) setEvidenceRunId(runId)
    setFailedTask(null)
    setGenTaskId(null)
    setGenerating(false)
    fetchShots()
  })

  const handleRetryGeneration = async () => {
    if (!failedTask) return
    try {
      const res = await taskApi.retry(failedTask.id)
      setFailedTask(null)
      setGenerating(true)
      setGenTaskId(res.data.id)
      message.info('已从成功批次后继续处理…')
    } catch {
      // 拦截器已提示
    }
  }

  const handleOpenEvidence = useCallback(async () => {
    if (!evidenceRunId) return
    try {
      const res = await storyboardApi.evidenceRun(projectId, evidenceRunId)
      setEvidenceRun(res.data)
      setEvidenceModalOpen(true)
    } catch {
      // 拦截器已提示
    }
  }, [evidenceRunId, projectId])

  const handleApproveEvidence = async () => {
    if (!evidenceRunId) return
    try {
      const res = await storyboardApi.approveEvidence(projectId, evidenceRunId, undefined, true)
      if (res.data.task_id) {
        setGenTaskId(res.data.task_id)
        setGenerating(true)
        setEvidenceModalOpen(false)
        message.info('证据已通过，正在继续生成解说词…')
      }
    } catch {
      // 拦截器已提示
    }
  }

  const handleGenerate = () => {
    genForm.setFieldsValue({
      section_count: 56,
      tone: '专业庄重',
      target_duration_seconds: 540,
      video_purpose: '投标答辩',
      include_company_intro: false,
      include_construction_simulation: true,
      chars_per_minute: 215,
      generation_mode: 'multi_stage',
      custom_requirements: '',
      predefined_outline: '',
      target_beat_count: 120,
      evidence_batch_chars: 9000,
      evidence_concurrency: 3,
      evidence_auto_approve: true,
      strict_fact_mode: true,
    })
    setGenModalOpen(true)
  }

  const handleGenerateSubmit = async () => {
    const values = await genForm.validateFields()
    setGenerating(true)
    setGenModalOpen(false)
    try {
      const res = await storyboardApi.generate(projectId, values)
      setGenTaskId(res.data.task_id)
      message.info('解说词智能拆解任务已提交，正在处理…')
    } catch {
      setGenerating(false)
    }
  }

  const handleEdit = (shot: StoryboardShot) => {
    setEditShot(shot)
    editForm.setFieldsValue({
      title: shot.title,
      section: shot.section,
      narration: shot.narration,
      visual_type: shot.visual_type,
      visual_description: shot.visual_description,
      duration_seconds: shot.duration_seconds,
      source_page: shot.source_page,
      fact_check_status: shot.fact_check_status,
    })
  }

  const handleAdd = () => {
    addForm.setFieldsValue({
      insert_at: shots.length + 1,
      section: '施工方案',
      duration_seconds: 20,
      visual_type: 'bim_animation',
      fact_check_status: 'unverified',
    })
    setAddModalOpen(true)
  }

  const handleAddSubmit = async () => {
    const values = await addForm.validateFields()
    try {
      await storyboardApi.create(projectId, { ...values, sequence: values.insert_at })
      message.success('分镜已添加')
      setAddModalOpen(false)
      fetchShots()
    } catch {
      // 拦截器已提示
    }
  }

  const handleSaveEdit = async () => {
    if (!editShot) return
    const values = await editForm.validateFields()
    try {
      await storyboardApi.update(projectId, editShot.id, values)
      message.success('已保存')
      setEditShot(null)
      fetchShots()
    } catch {
      // 拦截器已提示
    }
  }

  const handleDocumentInput = (shotId: string, event: { currentTarget: HTMLDivElement }) => {
    const narration = (event.currentTarget.innerText || '').replace(/\u00a0/g, ' ')
    setDocumentDrafts((current) => ({ ...current, [shotId]: narration }))
    setDocumentDirty(true)
  }

  const handleSaveDocument = async () => {
    const updates = shots.map((shot) => ({
      shot_id: shot.id,
      narration: (documentRefs.current[shot.id]?.innerText ?? documentDrafts[shot.id] ?? '').replace(/\u00a0/g, ' '),
    }))
    const changed = updates.filter((item) => item.narration !== (shots.find((shot) => shot.id === item.shot_id)?.narration || ''))
    if (changed.length === 0) {
      setDocumentDirty(false)
      message.info('文稿没有新的修改')
      return
    }
    setSavingDocument(true)
    try {
      const result = await storyboardApi.updateDocument(projectId, updates)
      setDocumentDirty(false)
      message.success(`已保存 ${result.data.updated_count} 个分镜，字幕断句已同步`)
      fetchShots()
    } catch {
      // 拦截器已提示
    } finally {
      setSavingDocument(false)
    }
  }

  const handleOpenResegment = () => {
    if (documentDirty) {
      message.warning('请先保存文稿，再让 AI 重新调整分镜')
      return
    }
    resegmentForm.setFieldsValue({
      target_shot_count: shots.length,
      chars_per_minute: 215,
      instructions: '',
    })
    setResegmentModalOpen(true)
  }

  const handleResegmentSubmit = async () => {
    const values = await resegmentForm.validateFields()
    setResegmentModalOpen(false)
    setGenerating(true)
    try {
      const result = await storyboardApi.resegment(projectId, values)
      setGenTaskId(result.data.task_id)
      message.info('AI 正在根据正文重新调整分镜…')
    } catch {
      setGenerating(false)
    }
  }

  const handleRestore = async (shot: StoryboardShot, revision: number) => {
    try {
      await storyboardApi.restore(projectId, shot.id, revision)
      message.success('已恢复历史版本')
      setHistoryShot(null)
      fetchShots()
    } catch {
      // 拦截器已提示
    }
  }

  const handleDelete = async (shotId: string) => {
    try {
      await storyboardApi.remove(projectId, shotId)
      message.success('已删除')
      fetchShots()
    } catch {
      // 拦截器已提示
    }
  }

  const handleMove = async (index: number, dir: -1 | 1) => {
    const target = index + dir
    if (target < 0 || target >= shots.length) return
    const next = [...shots]
    ;[next[index], next[target]] = [next[target], next[index]]
    const reordered = next.map((s, i) => ({ ...s, sequence: i + 1 }))
    setShots(reordered)
    try {
      await storyboardApi.reorder(projectId, reordered.map((s) => s.id))
      fetchShots()
    } catch {
      fetchShots()
    }
  }

  const handleRegenerate = async (shot: StoryboardShot) => {
    try {
      await storyboardApi.regenerate(projectId, shot.id, shot.title)
      message.success('重新生成完成')
      fetchShots()
    } catch {
      // 拦截器已提示
    }
  }

  const handleDuplicate = async (shot: StoryboardShot) => {
    try {
      const newShot: Partial<StoryboardShot> = {
        title: shot.title ? `${shot.title}(副本)` : '副本',
        section: shot.section,
        narration: shot.narration,
        duration_seconds: shot.duration_seconds,
        visual_type: shot.visual_type,
        visual_prompt: shot.visual_prompt,
        visual_description: shot.visual_description,
        image_prompt: shot.image_prompt,
        video_prompt: shot.video_prompt,
        source_references: shot.source_references,
        scoring_point_ids: shot.scoring_point_ids,
        fact_check_status: shot.fact_check_status,
        sequence: Math.max(...shots.map((s) => s.sequence), 0) + 1,
      }
      await storyboardApi.create(projectId, newShot)
      message.success('已复制，可在编辑中调整内容')
      fetchShots()
    } catch {
      // 拦截器已提示
    }
  }

  const unverifiedShots = shots.filter((s) => s.fact_check_status === 'unverified' || s.fact_check_status === 'conflict').length
  const beatsByShot = beats.reduce<Record<string, NarrationBeat[]>>((result, beat) => {
    if (!beat.shot_id) return result
    ;(result[beat.shot_id] ||= []).push(beat)
    return result
  }, {})
  const draftNarration = (shot: StoryboardShot) => documentDrafts[shot.id] ?? shot.narration ?? ''
  const shotStartTimes: Record<string, number> = {}
  let timelineCursor = 0
  shots.forEach((shot) => {
    shotStartTimes[shot.id] = timelineCursor
    timelineCursor += Number(shot.duration_seconds || 0)
  })
  const totalTimelineSeconds = timelineCursor
  const previewParagraphs: { text: string; sectionBreak: boolean }[] = []
  let previousPreviewSection: string | undefined
  shots.forEach((shot) => {
    const paragraphs = splitPreviewParagraphs(draftNarration(shot))
    paragraphs.forEach((text, index) => {
      previewParagraphs.push({
        text,
        sectionBreak: index === 0 && Boolean(previousPreviewSection && shot.section && shot.section !== previousPreviewSection),
      })
    })
    previousPreviewSection = shot.section
  })

  const handleExportText = () => {
    const content = previewParagraphs.map((paragraph) => paragraph.text).join('\n\n')
    if (!content.trim()) {
      message.info('当前没有可导出的正文')
      return
    }
    const blob = new Blob([`\uFEFF${content}`], { type: 'text/plain;charset=utf-8' })
    const url = URL.createObjectURL(blob)
    const anchor = document.createElement('a')
    anchor.href = url
    anchor.download = '解说词文稿.txt'
    anchor.click()
    URL.revokeObjectURL(url)
    message.success('文稿已导出为 TXT')
  }

  useEffect(() => {
    if (unverifiedShots > 0) {
      upsertNotice({
        key: 'storyboard:unverified',
        tone: 'warning',
        title: `${unverifiedShots} 个分镜包含未验证事实`,
        description: '建议在参数台账中确认来源，或编辑分镜补充引用。',
        action: (
          <Button size="small" onClick={() => navigate(`/project/${projectId}/facts`)}>
            前往参数台账
          </Button>
        ),
      })
    } else {
      removeNotice('storyboard:unverified')
    }
  }, [navigate, projectId, removeNotice, unverifiedShots, upsertNotice])

  useEffect(() => {
    if (!evidenceRunId) {
      removeNotice('storyboard:evidence')
      return
    }
    upsertNotice({
      key: 'storyboard:evidence',
      tone: 'success',
      title: '全文证据索引已建立',
      description: '可以查看批次进度和解说词引用来源。',
      action: <Button size="small" onClick={handleOpenEvidence}>查看证据与来源</Button>,
    })
  }, [evidenceRunId, handleOpenEvidence, removeNotice, upsertNotice])

  useEffect(() => {
    if (documentDirty) {
      upsertNotice({
        key: 'storyboard:document-dirty',
        tone: 'warning',
        title: '文稿有未保存修改',
        description: '保存后才会同步分镜卡片、字幕和配音状态。',
        action: (
          <Button size="small" onClick={() => navigate(`/project/${projectId}/storyboard`)}>
            返回解说词
          </Button>
        ),
      })
    } else {
      removeNotice('storyboard:document-dirty')
    }
  }, [documentDirty, navigate, projectId, removeNotice, upsertNotice])

  const columns: ColumnsType<StoryboardShot> = [
    {
      title: '序号',
      dataIndex: 'sequence',
      width: 70,
      render: (v: number) => (
        <Space direction="vertical" size={0}>
          <b>{v}</b>
          <Space size={0}>
            <Button aria-label="上移分镜" title="上移分镜" size="small" type="text" icon={<UpOutlined />} onClick={() => handleMove(v - 1, -1)} />
            <Button aria-label="下移分镜" title="下移分镜" size="small" type="text" icon={<DownOutlined />} onClick={() => handleMove(v - 1, 1)} />
          </Space>
        </Space>
      ),
    },
    {
      title: '标题/解说词',
      dataIndex: 'narration',
      className: 'storyboard-narration-column',
      render: (v: string, r: StoryboardShot) => (
        <Space direction="vertical" size={4} className="storyboard-narration-cell">
          <Space wrap size={[6, 4]}>
            {r.title && <b>{r.title}</b>}
            {r.section && <Tag color="blue">{r.section}</Tag>}
            <FactTag status={r.fact_check_status} />
            {r.source_references && r.source_references.length > 0 && (
              <Tag icon={<LinkOutlined />} color="geekblue">
                {r.source_references.length} 处来源
              </Tag>
            )}
          </Space>
          <Text type="secondary" className="storyboard-narration-text" ellipsis={{ tooltip: v }}>
            {v}
          </Text>
          <Space size={[4, 2]} wrap>
            {r.duration_seconds && (
              <Text type="secondary" style={{ fontSize: 12 }}>
                时长 {r.duration_seconds}s
              </Text>
            )}
            {r.visual_type && (
              <Tag style={{ fontSize: 11 }}>
                {VISUAL_TYPES.find((t) => t.value === r.visual_type)?.label || r.visual_type}
              </Tag>
            )}
            {r.scoring_point_ids && r.scoring_point_ids.length > 0 && (
              <Space size={2} wrap>
                {r.scoring_point_ids.slice(0, 3).map((sid) => (
                  <Tag key={sid} color="green" style={{ fontSize: 11 }}>
                    {scoringNames[sid] || '评分点'}
                  </Tag>
                ))}
              </Space>
            )}
          </Space>
        </Space>
      ),
    },
    {
      title: '来源页码',
      width: 90,
      align: 'center' as const,
      responsive: ['xl'],
      render: (_: unknown, r: StoryboardShot) => {
        const pages = (r.source_references || []).map((ref) => ref.page).filter(Boolean) as number[]
        if (pages.length === 0) return <Text type="secondary">无</Text>
        return (
          <Space size={2} wrap>
            {[...new Set(pages)].slice(0, 3).map((p) => (
              <Tag key={p} color="orange">
                P{p}
              </Tag>
            ))}
          </Space>
        )
      },
    },
    {
      title: '配音',
      dataIndex: 'audio_asset_id',
      width: 80,
      align: 'center' as const,
      responsive: ['xl'],
      render: (v: string) => (v ? <Tag color="success">已生成</Tag> : <Text type="secondary">无</Text>),
    },
    {
      title: '操作',
      width: 190,
      render: (_: unknown, r: StoryboardShot) => (
        <Space size={6} className="storyboard-actions">
          <Button size="small" type="link" onClick={() => handleEdit(r)}>编辑</Button>
          <Dropdown
            trigger={['click']}
            placement="bottomRight"
            menu={{
              items: [
                { key: 'history', icon: <HistoryOutlined />, label: '版本历史' },
                { key: 'duplicate', icon: <CopyOutlined />, label: '复制分镜' },
                { type: 'divider' },
                { key: 'regenerate', icon: <ReloadOutlined />, label: '重新生成解说词' },
                { key: 'assets', icon: <PictureOutlined />, label: '前往素材工作区' },
                { type: 'divider' },
                { key: 'delete', danger: true, icon: <DeleteOutlined />, label: '删除分镜' },
              ],
              onClick: ({ key }) => {
                if (key === 'history') setHistoryShot(r)
                if (key === 'duplicate') handleDuplicate(r)
                if (key === 'regenerate') handleRegenerate(r)
                if (key === 'assets') navigate(`/project/${projectId}/render`)
                if (key === 'delete') {
                  Modal.confirm({
                    title: '删除该分镜？',
                    content: '删除后无法恢复，请确认仍要继续。',
                    okText: '删除',
                    okType: 'danger',
                    cancelText: '取消',
                    onOk: () => handleDelete(r.id),
                  })
                }
              },
            }}
          >
            <Button size="small" icon={<MoreOutlined />}>更多 <DownOutlined /></Button>
          </Dropdown>
        </Space>
      ),
    },
  ]

  const documentEditor = (
    <div className="narration-document-editor">
      {shots.map((shot, index) => {
        const shotBeats = beatsByShot[shot.id] || []
        const previousSection = index > 0 ? shots[index - 1].section : undefined
        return (
          <div key={shot.id} className="narration-document-block">
            {showShotMarkers && shot.section && shot.section !== previousSection && (
              <div className="narration-document-section">{shot.section}</div>
            )}
            {showShotMarkers && (
              <div className="narration-document-marker">
                <Tag color="blue">镜头 {shot.sequence}</Tag>
                <Text strong>{shot.title || '未命名分镜'}</Text>
                <Text className="narration-document-timecode">{formatTimecode(shotStartTimes[shot.id])}</Text>
                {shot.duration_seconds ? <Text type="secondary">预计 {shot.duration_seconds.toFixed(1)} 秒</Text> : null}
                <FactTag status={shot.fact_check_status} />
              </div>
            )}
            {!showShotMarkers && (
              <div className="narration-document-time-only">{formatTimecode(shotStartTimes[shot.id])}</div>
            )}
            <div
              ref={(node) => { documentRefs.current[shot.id] = node }}
              className="narration-document-text"
              contentEditable
              suppressContentEditableWarning
              spellCheck={false}
              onInput={(event) => handleDocumentInput(shot.id, event)}
            >
              {draftNarration(shot)}
            </div>
            {showSubtitleBreaks && (
              <div className="narration-subtitle-breaks">
                {shotBeats.length > 0 ? shotBeats.map((beat) => (
                  <span key={beat.id} className="narration-subtitle-beat">
                    <span className="narration-subtitle-time">{formatTimecode(beat.start_time)}</span>
                    {beat.narration}
                  </span>
                )) : <Text type="secondary">保存文稿后生成字幕断句</Text>}
              </div>
            )}
            {showSourceMarkers && shot.source_references && shot.source_references.length > 0 && (
              <div className="narration-document-sources">
                <LinkOutlined />
                {shot.source_references.slice(0, 4).map((ref, refIndex) => (
                  <Tag key={`${shot.id}-source-${refIndex}`} color="geekblue">
                    {ref.documentName || '来源'} {ref.page ? `P${ref.page}` : ref.locationLabel || ''}
                  </Tag>
                ))}
              </div>
            )}
          </div>
        )
      })}
    </div>
  )

  const previewEditor = (
    <div className="narration-preview-editor">
      <article className="narration-preview-text">
        {previewParagraphs.map((paragraph, index) => (
          <p
            key={`preview-paragraph-${index}`}
            className={paragraph.sectionBreak ? 'narration-preview-paragraph narration-preview-section-break' : 'narration-preview-paragraph'}
          >
            {paragraph.text}
          </p>
        ))}
      </article>
    </div>
  )

  return (
    <div>
      <div className="page-header storyboard-page-header">
        <div className="page-heading">
          <Title level={3} style={{ marginBottom: 6 }}>
            解说词与分镜
          </Title>
          <Text type="secondary" className="page-description">
            AI 根据已确认的工程事实与评分点智能拆解解说词，支持来源跳转与人工编辑
          </Text>
        </div>
        <Space className="page-actions">
          <Button icon={<PlusOutlined />} onClick={handleAdd}>添加分镜</Button>
          <Button type="primary" icon={<SettingOutlined />} onClick={handleGenerate} loading={generating}>
            智能生成解说词
          </Button>
        </Space>
      </div>

      {summary && (
        <div className="storyboard-summary-grid">
          <Card size="small" className="summary-card summary-card-blue">
            <Statistic title="分镜数" value={summary.shot_count} />
          </Card>
          <Card size="small" className="summary-card summary-card-purple">
            <Statistic title="总时长" value={summary.total_duration_seconds} suffix="秒" />
          </Card>
          <Card size="small" className="summary-card summary-card-neutral">
            <Statistic title="总字数" value={summary.total_narration_characters} suffix="字" />
          </Card>
          <Card size="small" className="summary-card summary-card-orange">
            <Statistic title="评分点覆盖率" value={Math.round(summary.scoring_coverage_rate * 100)} suffix="%" />
          </Card>
          <Card size="small" className="summary-card summary-card-green">
            <Statistic title="未验证分镜" value={unverifiedShots} valueStyle={{ color: unverifiedShots > 0 ? '#C23A3A' : '#2F7D5B' }} />
          </Card>
        </div>
      )}

      <Card className="storyboard-table-card" bodyStyle={{ padding: 0 }}>
        {shots.length === 0 ? (
          <Empty className="storyboard-empty" description="暂无分镜，可先生成解说词或手动添加">
            <Button type="primary" icon={<PlayCircleOutlined />} onClick={handleGenerate}>
              生成解说词
            </Button>
          </Empty>
        ) : (
          <>
            <div className="storyboard-editor-toolbar">
              <Space wrap>
                <Segmented
                  value={viewMode}
                  onChange={(value) => setViewMode(value as StoryboardViewMode)}
                  options={[{ label: '连续文稿', value: 'document' }, { label: '文稿预览', value: 'preview' }, { label: '分镜卡片', value: 'storyboard' }]}
                />
                {viewMode === 'document' && (
                  <>
                    <Switch checked={showShotMarkers} onChange={setShowShotMarkers} checkedChildren="分镜" unCheckedChildren="分镜" />
                    <Switch checked={showSubtitleBreaks} onChange={setShowSubtitleBreaks} checkedChildren="字幕" unCheckedChildren="字幕" />
                    <Switch checked={showSourceMarkers} onChange={setShowSourceMarkers} checkedChildren="来源" unCheckedChildren="来源" />
                    <Button type="primary" onClick={handleSaveDocument} loading={savingDocument} disabled={!documentDirty}>
                      保存文稿
                    </Button>
                    <Button onClick={handleOpenResegment} disabled={documentDirty || generating}>
                      AI重新分镜
                    </Button>
                  </>
                )}
                {viewMode === 'preview' && (
                  <Button icon={<DownloadOutlined />} onClick={handleExportText}>
                    导出文稿
                  </Button>
                )}
              </Space>
              {(viewMode === 'document' || viewMode === 'preview') && (
                <Text type="secondary">
                  {summary?.total_narration_characters || 0} 字 · 总时长 {formatTimecode(totalTimelineSeconds)}
                  {viewMode === 'document' ? ` · ${summary?.beat_count || beats.length} 条字幕节拍` : ''}
                </Text>
              )}
            </div>
            {viewMode === 'document' ? documentEditor : viewMode === 'preview' ? previewEditor : (
          <Table<StoryboardShot>
            rowKey="id"
            loading={loading}
            dataSource={shots}
            columns={columns}
            pagination={false}
            tableLayout="fixed"
            className="storyboard-table"
            expandable={{
              expandedRowRender: (r) => (
                <div style={{ padding: '0 8px' }}>
                  <Space direction="vertical" style={{ width: '100%' }} size={4}>
                    {r.visual_description && (
                      <Text>画面：{r.visual_description}</Text>
                    )}
                    {r.image_prompt && (
                      <Text type="secondary" style={{ fontSize: 12 }}>图片提示词：{r.image_prompt}</Text>
                    )}
                    {r.source_references && r.source_references.length > 0 && (
                      <div>
                        <Text strong style={{ fontSize: 12 }}>来源引用：</Text>
                        {r.source_references.map((ref, i) => (
                          <div key={i} style={{ marginLeft: 8, marginTop: 4 }}>
                            <Tag color="geekblue">{ref.documentName}</Tag>
                            <Text style={{ fontSize: 12 }}>
                              P{ref.page} {ref.quote ? `「${ref.quote}」` : ''}
                            </Text>
                          </div>
                        ))}
                      </div>
                    )}
                  </Space>
                </div>
              ),
            }}
          />
            )}
          </>
        )}
      </Card>

      <Modal
        title="AI 重新调整分镜"
        open={resegmentModalOpen}
        onOk={handleResegmentSubmit}
        onCancel={() => setResegmentModalOpen(false)}
        okText="开始调整"
        confirmLoading={generating}
        width={560}
      >
        <Text type="secondary" style={{ display: 'block', marginBottom: 16 }}>
          正文保持不变，只重新划分镜头边界、章节标题和画面组织。已有画面素材会尽量保留。
        </Text>
        <Form form={resegmentForm} layout="vertical">
          <Form.Item
            name="target_shot_count"
            label="目标分镜数量"
            rules={[{ required: true, message: '请输入目标分镜数量' }]}
          >
            <InputNumber min={1} max={100} style={{ width: '100%' }} />
          </Form.Item>
          <Form.Item name="chars_per_minute" label="参考语速（字/分钟）">
            <InputNumber min={120} max={400} style={{ width: '100%' }} />
          </Form.Item>
          <Form.Item name="instructions" label="调整要求">
            <Input.TextArea rows={4} placeholder="例如：项目概况集中在前两镜，主体结构按施工顺序拆开，机电穿插单独成章。" />
          </Form.Item>
        </Form>
      </Modal>

      {/* 生成配置弹窗 */}
      <Modal
        title="智能拆解解说词"
        open={genModalOpen}
        onOk={handleGenerateSubmit}
        onCancel={() => setGenModalOpen(false)}
        okText="开始生成"
        confirmLoading={generating}
        width={560}
      >
        <Text type="secondary" style={{ display: 'block', marginBottom: 16 }}>
          将先核对资料，再编排章节、分章写作并复核事实。未能核实的内容不会写成确定结论。
        </Text>
        <Form form={genForm} layout="vertical">
          <Form.Item
            name="predefined_outline"
            label="预设解说词大纲"
            extra="可选。填写后AI按你的顺序整理证据、编排章节和写稿；留空则根据标书原文标题、证据分布和施工逻辑自动提炼，不限定章节数量。"
          >
            <Input.TextArea
              rows={8}
              placeholder={'可留空自动提炼；或填写：\n1. 项目概况与总体部署\n2. 基坑土方与基础施工\n3. 主体结构与专业穿插'}
            />
          </Form.Item>
          <Row gutter={12}>
            <Col span={12}>
              <Form.Item name="target_duration_seconds" label="视频目标时长（秒）">
                <InputNumber min={60} max={1800} style={{ width: '100%' }} />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item name="section_count" label="分镜数量">
                <InputNumber min={8} max={100} style={{ width: '100%' }} />
              </Form.Item>
            </Col>
          </Row>
          <Form.Item name="tone" label="解说风格">
            <Select
              options={['专业庄重', '科技感', '简洁明快', '宏大叙事'].map((t) => ({ label: t, value: t }))}
            />
          </Form.Item>
          <Form.Item name="video_purpose" label="视频用途">
            <Select
              options={['投标答辩', '企业宣传', '评审汇报', '项目汇报'].map((t) => ({ label: t, value: t }))}
            />
          </Form.Item>
          <Form.Item name="chars_per_minute" label="每分钟参考字数">
            <InputNumber min={120} max={400} style={{ width: '100%' }} />
          </Form.Item>
          <Row gutter={12}>
            <Col span={12}>
              <Form.Item name="target_beat_count" label="旁白短句数量">
                <InputNumber min={20} max={240} style={{ width: '100%' }} />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item name="evidence_batch_chars" label="全文批次大小">
                <InputNumber min={3000} max={16000} step={500} style={{ width: '100%' }} />
              </Form.Item>
            </Col>
          </Row>
          <Form.Item name="evidence_concurrency" label="证据批次并发数">
            <InputNumber min={1} max={8} style={{ width: '100%' }} />
          </Form.Item>
          <Form.Item name="custom_requirements" label="额外要求">
            <Input.TextArea rows={3} placeholder="例如：重点展开土方开挖、塔吊布置与机电穿插；结尾控制在 20 秒内" />
          </Form.Item>
          <Row gutter={12}>
            <Col span={12}>
              <Form.Item name="include_company_intro" label="包含企业介绍" valuePropName="checked">
                <Switch />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item name="include_construction_simulation" label="包含施工推演" valuePropName="checked">
                <Switch />
              </Form.Item>
            </Col>
          </Row>
          <Row gutter={12}>
            <Col span={12}>
              <Form.Item name="evidence_auto_approve" label="自动通过证据" valuePropName="checked">
                <Switch />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item name="strict_fact_mode" label="严格事实模式" valuePropName="checked">
                <Switch />
              </Form.Item>
            </Col>
          </Row>
        </Form>
      </Modal>

      <Modal
        title="全文证据审核"
        open={evidenceModalOpen}
        onCancel={() => setEvidenceModalOpen(false)}
        footer={[
          <Button key="close" onClick={() => setEvidenceModalOpen(false)}>关闭</Button>,
          <Button key="approve" type="primary" onClick={handleApproveEvidence}>通过并继续生成</Button>,
        ]}
        width={760}
      >
        {evidenceRun && (
          <>
            <Descriptions size="small" column={3} bordered>
              <Descriptions.Item label="运行状态">{evidenceRun.run?.status}</Descriptions.Item>
              <Descriptions.Item label="批次进度">{evidenceRun.run?.completed_batches}/{evidenceRun.run?.total_batches}</Descriptions.Item>
              <Descriptions.Item label="证据条数">{evidenceRun.run?.evidence_count}</Descriptions.Item>
            </Descriptions>
            <List
              size="small"
              dataSource={(evidenceRun.evidence || []).slice(0, 80)}
              renderItem={(item: any) => (
                <List.Item>
                  <Space direction="vertical" size={2} style={{ width: '100%' }}>
                    <Space wrap>
                      <Tag color="blue">{item.topic}</Tag>
                      <Tag>{item.fact_check_status}</Tag>
                      <Text type="secondary">{item.source_reference?.documentName || '来源文件'} {item.source_reference?.page ? `P${item.source_reference.page}` : item.source_reference?.locationLabel || ''}</Text>
                    </Space>
                    <Text>{item.fact}</Text>
                  </Space>
                </List.Item>
              )}
            />
          </>
        )}
      </Modal>

      <Modal
        title="添加分镜"
        open={addModalOpen}
        onOk={handleAddSubmit}
        onCancel={() => setAddModalOpen(false)}
        okText="添加"
        width={640}
      >
        <Form form={addForm} layout="vertical">
          <Row gutter={12}>
            <Col span={12}>
              <Form.Item name="insert_at" label="插入位置" rules={[{ required: true, message: '请选择插入位置' }]}>
                <InputNumber min={1} max={shots.length + 1} style={{ width: '100%' }} />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item name="duration_seconds" label="预计时长（秒）" rules={[{ required: true, message: '请输入时长' }]}>
                <InputNumber min={1} max={120} style={{ width: '100%' }} />
              </Form.Item>
            </Col>
          </Row>
          <Form.Item name="title" label="分镜标题" rules={[{ required: true, message: '请输入标题' }]}>
            <Input placeholder="例如：地下室结构施工" />
          </Form.Item>
          <Form.Item name="section" label="章节">
            <Select options={SECTION_OPTIONS.map((s) => ({ label: s, value: s }))} />
          </Form.Item>
          <Form.Item name="narration" label="解说词" rules={[{ required: true, message: '请输入解说词' }]}>
            <Input.TextArea rows={4} placeholder="写清施工对象、作业顺序和控制要点" />
          </Form.Item>
          <Row gutter={12}>
            <Col span={12}>
              <Form.Item name="visual_type" label="画面类型">
                <Select options={VISUAL_TYPES} />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item name="fact_check_status" label="事实状态">
                <Select options={Object.entries(FACT_STATUS_MAP).map(([k, v]) => ({ label: v.label, value: k }))} />
              </Form.Item>
            </Col>
          </Row>
          <Form.Item name="visual_description" label="画面描述">
            <Input.TextArea rows={2} placeholder="例如：BIM 展示地下室分区、流水方向与吊装路线" />
          </Form.Item>
        </Form>
      </Modal>

      {/* 编辑弹窗 */}
      <Modal
        title={`编辑分镜 #${editShot?.sequence || ''}`}
        open={!!editShot}
        onOk={handleSaveEdit}
        onCancel={() => setEditShot(null)}
        width={640}
      >
        <Form form={editForm} layout="vertical">
          <Form.Item name="title" label="分镜标题">
            <Input />
          </Form.Item>
          <Form.Item name="section" label="章节">
            <Select options={SECTION_OPTIONS.map((s) => ({ label: s, value: s }))} allowClear />
          </Form.Item>
          <Form.Item name="narration" label="解说词" rules={[{ required: true, message: '请输入解说词' }]}>
            <Input.TextArea rows={4} />
          </Form.Item>
          <Row gutter={12}>
            <Col span={12}>
              <Form.Item name="visual_type" label="画面类型">
                <Select options={VISUAL_TYPES} allowClear />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item name="duration_seconds" label="预计时长（秒）">
                <InputNumber min={1} max={120} style={{ width: '100%' }} />
              </Form.Item>
            </Col>
          </Row>
          <Form.Item name="visual_description" label="画面描述">
            <Input.TextArea rows={2} />
          </Form.Item>
          <Form.Item name="source_page" label="来源页码（招标文件）">
            <InputNumber min={1} style={{ width: '100%' }} placeholder="可选" />
          </Form.Item>
          <Form.Item name="fact_check_status" label="事实校验状态">
            <Select
              options={Object.entries(FACT_STATUS_MAP).map(([k, v]) => ({ label: v.label, value: k }))}
              allowClear
            />
          </Form.Item>
        </Form>
      </Modal>

      {/* 历史版本弹窗 */}
      <Modal
        title={`历史版本 - ${historyShot?.title || '分镜'}`}
        open={!!historyShot}
        onCancel={() => setHistoryShot(null)}
        footer={null}
        width={680}
      >
        {(historyShot?.versions || []).length === 0 && <Empty description="暂无历史版本" />}
        {historyShot?.versions?.map((v) => (
          <Card key={v.revision} size="small" style={{ marginBottom: 8 }}>
            <Space direction="vertical" style={{ width: '100%' }}>
              <Space>
                <Tag color={v.source === 'ai' ? 'blue' : 'green'}>
                  版本 {v.revision} · {v.source === 'ai' ? 'AI生成' : '人工编辑'}
                </Tag>
                <Text type="secondary" style={{ fontSize: 12 }}>{v.created_at}</Text>
              </Space>
              <Paragraph style={{ marginBottom: 0 }}>{v.narration}</Paragraph>
              {v.visual_prompt && (
                <Text type="secondary" style={{ fontSize: 12 }}>画面提示词：{v.visual_prompt}</Text>
              )}
              <Button
                size="small"
                type="primary"
                ghost
                onClick={() => handleRestore(historyShot, v.revision)}
              >
                恢复此版本
              </Button>
            </Space>
          </Card>
        ))}
      </Modal>
    </div>
  )
}

function FactTag({ status }: { status?: string }) {
  if (!status) return null
  const item = FACT_STATUS_MAP[status] || { label: status, color: 'default' }
  return <Tag color={item.color}>{item.label}</Tag>
}
