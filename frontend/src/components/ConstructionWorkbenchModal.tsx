import { useMemo, useState, type ReactNode } from 'react'
import { Alert, Button, Card, Divider, Input, InputNumber, Modal, Progress, Space, Tag, Typography } from 'antd'
import {
  ArrowLeftOutlined,
  ArrowRightOutlined,
  CheckCircleFilled,
  DeleteOutlined,
  LockOutlined,
  PlusOutlined,
  SafetyOutlined,
  SendOutlined,
  WarningOutlined,
} from '@ant-design/icons'
import type { ReferenceImage } from '../api/types'

const { Text, Title } = Typography
const { TextArea } = Input

type Recipe = Record<string, any>
type TimelineRow = { from: number; to: number; instruction: string }

interface ConstructionWorkbenchModalProps {
  open: boolean
  onClose: () => void
  onApply: () => void | Promise<void>
  applyLoading?: boolean
  recipe: Recipe | null
  onChange: (next: Recipe) => void
  prompt: string
  compiledPrompt: string
  negativePrompt: string
  provider: string
  modelName: string
  duration: number
  generationMode?: 'image_to_video' | 'first_last_frame_video' | 'multi_reference_video'
  firstFrame?: ReferenceImage | null
  lastFrame?: ReferenceImage | null
  referenceImages?: ReferenceImage[]
}

const fallbackTimeline: TimelineRow[] = [
  { from: 0, to: 20, instruction: '确认前置条件与作业面' },
  { from: 20, to: 80, instruction: '按声明的施工顺序推进主工序' },
  { from: 80, to: 100, instruction: '完成目标状态并定格' },
]

const fallbackCameraTimeline: TimelineRow[] = [
  { from: 0, to: 20, instruction: '固定机位建立全景' },
  { from: 20, to: 80, instruction: '沿施工工作面稳定跟拍' },
  { from: 80, to: 100, instruction: '减速定格，不切镜' },
]

const stepMeta = [
  { title: '工程事实', description: '明确不可被模型改写的工程前提' },
  { title: '施工单元', description: '把镜头约束到一个 WBS 作业单元' },
  { title: '状态转换', description: '定义从什么状态施工到什么状态' },
  { title: '双时间轴', description: '同步配置施工进度与摄影表现' },
  { title: '空间与安全', description: '锁定空间关系、临设与质量要求' },
  { title: 'Seedance 投喂', description: '检查并应用最终模型提示词' },
]

const asList = (value: any, fallback: string[] = []) => {
  if (Array.isArray(value) && value.length) return value.map(String).filter(Boolean)
  if (typeof value === 'string' && value.trim()) {
    return value.split(/[\n；;]/).map((item) => item.trim()).filter(Boolean)
  }
  return fallback
}

const listText = (value: any) => asList(value).join('\n')
const parseList = (value: string) => value.split(/[\n；;]/).map((item) => item.trim()).filter(Boolean)

const normalizeRecipe = (value: Recipe | null): Recipe => ({
  recipe_version: 2,
  ...(value || {}),
  construction_mode: 'construction_evolution',
  project_facts: { structure_type: '', current_stage: '', target_stage: '', fact_sources: [], ...(value?.project_facts || {}) },
  construction_unit: { wbs_code: '', work_item: '', work_zone: '', zone_mappings: [], objects: [], prerequisites: [], completion_state: [], ...(value?.construction_unit || {}) },
  state_transition: { start_state: '', end_state: '', allowed_changes: [], forbidden_jumps: [], ...(value?.state_transition || {}) },
  construction_timeline: Array.isArray(value?.construction_timeline) && value.construction_timeline.length ? value.construction_timeline : fallbackTimeline,
  camera_timeline: Array.isArray(value?.camera_timeline) && value.camera_timeline.length ? value.camera_timeline : fallbackCameraTimeline,
  spatial_anchors: Array.isArray(value?.spatial_anchors) ? value.spatial_anchors : [],
  temporary_works: { required: [], forbidden: [], ...(value?.temporary_works || {}) },
  safety_constraints: Array.isArray(value?.safety_constraints) ? value.safety_constraints : [],
  quality_constraints: Array.isArray(value?.quality_constraints) ? value.quality_constraints : [],
  acceptance_checks: Array.isArray(value?.acceptance_checks) ? value.acceptance_checks : [],
})

function Field({ label, hint, children }: { label: string; hint?: string; children: ReactNode }) {
  return (
    <label style={{ display: 'block' }}>
      <Text strong style={{ display: 'block', marginBottom: 6, fontSize: 12 }}>{label}</Text>
      {children}
      {hint && <Text type="secondary" style={{ display: 'block', marginTop: 5, fontSize: 11 }}>{hint}</Text>}
    </label>
  )
}

export function ConstructionWorkbenchContent({
  onClose,
  onApply,
  applyLoading = false,
  recipe,
  onChange,
  prompt,
  compiledPrompt,
  negativePrompt,
  modelName,
  duration,
  generationMode = 'first_last_frame_video',
  firstFrame,
  lastFrame,
  referenceImages = [],
}: ConstructionWorkbenchModalProps) {
  const [activeStep, setActiveStep] = useState(0)
  const current = useMemo(() => normalizeRecipe(recipe), [recipe])
  const facts = current.project_facts
  const unit = current.construction_unit
  const transition = current.state_transition
  const temporary = current.temporary_works
  const constructionTimeline = current.construction_timeline as TimelineRow[]
  const cameraTimeline = current.camera_timeline as TimelineRow[]
  const manualPrompt = typeof current.provider_prompt_override === 'string'
    ? current.provider_prompt_override
    : ''
  const manualOverride = Boolean(manualPrompt.trim())
  const providerPrompt = manualOverride ? manualPrompt : compiledPrompt || prompt
  const promptLength = providerPrompt.length
  const promptOverLimit = promptLength > 2000
  const promptTooVerbose = promptLength > 900
  const promptConcise = Boolean(providerPrompt) && promptLength <= 800
  const zoneMappings = asList(unit.zone_mappings)
  const activeConstructionPhases = constructionTimeline.filter((row) => {
    const text = String(row.instruction || '')
    return !/(建立|确认|定格|保持首帧|停止)/.test(text)
  }).length
  // 首尾帧仍是默认且唯一的生成通道；这里仅提示人工核对两帧是否确实代表同一施工对象。
  const frameReviewRisk = generationMode === 'first_last_frame_video' && activeConstructionPhases >= 3
  const framesReady = generationMode === 'multi_reference_video'
    ? referenceImages.length >= 2
    : generationMode === 'first_last_frame_video'
      ? Boolean(firstFrame && lastFrame)
      : Boolean(firstFrame)
  const frameRequirement = generationMode === 'multi_reference_video'
    ? '多参考图模式至少需要两张参考图'
    : generationMode === 'first_last_frame_video'
      ? '首尾帧模式必须同时选择首帧和尾帧'
      : '图生视频模式必须选择一张首帧'

  const update = (patch: Recipe) => {
    const next = { ...current, ...patch }
    // 前五步一旦发生变化，旧的人工终稿就不再代表当前配方，回到后端自动编译。
    if (!Object.prototype.hasOwnProperty.call(patch, 'provider_prompt_override')) {
      delete next.provider_prompt_override
    }
    onChange(next)
  }
  const updateNested = (key: string, patch: Recipe) => update({ [key]: { ...current[key], ...patch } })
  const updateFinalPrompt = (value: string) => onChange({ ...current, provider_prompt_override: value })
  const restoreAutomaticPrompt = () => {
    const next = { ...current }
    delete next.provider_prompt_override
    onChange(next)
  }

  const recipeChecks = [
    Boolean(facts.structure_type && facts.current_stage && facts.target_stage),
    Boolean(unit.wbs_code && unit.work_item && unit.work_zone),
    Boolean(transition.start_state && transition.end_state && asList(transition.allowed_changes).length),
    constructionTimeline.length > 0 && cameraTimeline.length > 0,
    asList(current.spatial_anchors).length > 0 && asList(current.safety_constraints).length > 0,
  ]
  const recipeReady = recipeChecks.every(Boolean)
  const stepDone = [...recipeChecks, recipeReady && Boolean(providerPrompt) && !promptOverLimit]
  const completion = Math.round((stepDone.filter(Boolean).length / stepDone.length) * 100)

  const listField = (
    label: string,
    value: any,
    onValue: (next: string[]) => void,
    placeholder: string,
    hint?: string,
  ) => (
    <Field label={label} hint={hint}>
      <TextArea
        value={listText(value)}
        onChange={(event) => onValue(parseList(event.target.value))}
        placeholder={placeholder}
        autoSize={{ minRows: 2, maxRows: 5 }}
      />
    </Field>
  )

  const timelinePreview = (rows: TimelineRow[], color: string) => (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 7 }}>
      {rows.map((row, index) => {
        const from = Math.max(0, Math.min(100, Number(row.from) || 0))
        const to = Math.max(from, Math.min(100, Number(row.to) || 100))
        return (
          <div key={`${index}-${row.instruction}`} style={{ display: 'grid', gridTemplateColumns: '72px minmax(0, 1fr)', alignItems: 'center', gap: 8 }}>
            <Text type="secondary" style={{ fontSize: 11 }}>{from}%–{to}%</Text>
            <div style={{ position: 'relative', height: 30, borderRadius: 4, background: '#eef2f7', overflow: 'hidden' }}>
              <div style={{ position: 'absolute', left: `${from}%`, width: `${Math.max(3, to - from)}%`, top: 4, bottom: 4, display: 'flex', alignItems: 'center', padding: '0 8px', borderRadius: 3, background: color, color: '#fff', fontSize: 11, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
                {row.instruction || `阶段 ${index + 1}`}
              </div>
            </div>
          </div>
        )
      })}
    </div>
  )

  const timelineEditor = (key: 'construction_timeline' | 'camera_timeline', rows: TimelineRow[], color: string, title: string) => {
    const changeRow = (index: number, patch: Partial<TimelineRow>) => {
      const next = rows.map((row, rowIndex) => rowIndex === index ? { ...row, ...patch } : row)
      update({ [key]: next })
    }
    const deleteRow = (index: number) => update({ [key]: rows.filter((_, rowIndex) => rowIndex !== index) })
    return (
      <Card size="small" styles={{ body: { padding: 14 } }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 11 }}>
          <Space size={7}><span style={{ width: 14, height: 5, background: color }} /><Text strong>{title}</Text></Space>
          <Button size="small" icon={<PlusOutlined />} onClick={() => update({ [key]: [...rows, { from: 0, to: 100, instruction: '' }] })}>增加阶段</Button>
        </div>
        {timelinePreview(rows, color)}
        <Divider style={{ margin: '12px 0' }} />
        <Space direction="vertical" size={8} style={{ width: '100%' }}>
          {rows.map((row, index) => (
            <div key={index} style={{ display: 'grid', gridTemplateColumns: '78px 78px minmax(180px, 1fr) 30px', gap: 7 }}>
              <InputNumber min={0} max={100} value={row.from} addonAfter="%" onChange={(value) => changeRow(index, { from: Number(value ?? 0) })} style={{ width: '100%' }} />
              <InputNumber min={0} max={100} value={row.to} addonAfter="%" onChange={(value) => changeRow(index, { to: Number(value ?? 100) })} style={{ width: '100%' }} />
              <Input value={row.instruction} onChange={(event) => changeRow(index, { instruction: event.target.value })} placeholder={key === 'construction_timeline' ? '这一段发生什么施工变化' : '这一段镜头如何运动'} />
              <Button danger type="text" icon={<DeleteOutlined />} disabled={rows.length === 1} onClick={() => deleteRow(index)} />
            </div>
          ))}
        </Space>
      </Card>
    )
  }

  const frameCards = [
    { label: '首帧 / 当前状态', frame: firstFrame },
    { label: '施工中间态', frame: referenceImages.find((item) => item.id !== firstFrame?.id && item.id !== lastFrame?.id) },
    { label: '尾帧 / 目标状态', frame: lastFrame },
  ]

  const renderStep = () => {
    if (activeStep === 0) return (
      <div style={{ display: 'grid', gap: 14 }}>
        <Alert type="info" showIcon message="这里只填写可核验的工程事实" description="这些字段会作为硬约束编译进提示词，防止模型擅自改变结构、阶段或施工对象。" />
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 14 }}>
          <Field label="结构形式"><Input value={facts.structure_type} onChange={(event) => updateNested('project_facts', { structure_type: event.target.value })} placeholder="例如：钢筋混凝土框架-核心筒" /></Field>
          <Field label="事实来源"><Input value={listText(facts.fact_sources)} onChange={(event) => updateNested('project_facts', { fact_sources: parseList(event.target.value) })} placeholder="例如：总平图；施工组织设计" /></Field>
          <Field label="当前阶段"><Input value={facts.current_stage} onChange={(event) => updateNested('project_facts', { current_stage: event.target.value })} placeholder="例如：地下室顶板完成" /></Field>
          <Field label="目标阶段"><Input value={facts.target_stage} onChange={(event) => updateNested('project_facts', { target_stage: event.target.value })} placeholder="例如：首层主体结构完成" /></Field>
        </div>
      </div>
    )

    if (activeStep === 1) return (
      <div style={{ display: 'grid', gap: 14 }}>
        <div style={{ display: 'grid', gridTemplateColumns: '0.7fr 1.3fr 1fr', gap: 14 }}>
          <Field label="WBS 编码"><Input value={unit.wbs_code} onChange={(event) => updateNested('construction_unit', { wbs_code: event.target.value })} placeholder="03.02.04" /></Field>
          <Field label="施工工序"><Input value={unit.work_item} onChange={(event) => updateNested('construction_unit', { work_item: event.target.value })} placeholder="例如：首层框架柱钢筋绑扎" /></Field>
          <Field label="作业区"><Input value={unit.work_zone} onChange={(event) => updateNested('construction_unit', { work_zone: event.target.value })} placeholder="例如：A区 1-5 轴" /></Field>
        </div>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 14 }}>
          {listField('施工对象', unit.objects, (next) => updateNested('construction_unit', { objects: next }), '每行一个对象，例如：框架柱\n梁板\n安全防护')}
          {listField('前置条件', unit.prerequisites, (next) => updateNested('construction_unit', { prerequisites: next }), '例如：测量放线完成\n作业面验收通过')}
          {listField('完成判据', unit.completion_state, (next) => updateNested('construction_unit', { completion_state: next }), '例如：构件位置正确\n节点连接完成')}
        </div>
        {listField(
          '施工分区画面定位',
          unit.zone_mappings,
          (next) => updateNested('construction_unit', { zone_mappings: next }),
          '每行一个可见位置，例如：①区=画面左上侧外围裙房\n②区=画面中央核心筒周边\n③区=画面右下侧剩余梁板',
          '只写“①区、②区、③区”模型无法定位；必须说明它在首尾帧中的可见位置和边界。',
        )}
      </div>
    )

    if (activeStep === 2) return (
      <div style={{ display: 'grid', gap: 14 }}>
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 44px 1fr', alignItems: 'stretch' }}>
          <Card size="small" title="开始状态"><TextArea value={transition.start_state} onChange={(event) => updateNested('state_transition', { start_state: event.target.value })} placeholder="镜头开始时，已建成与未建成内容分别是什么" autoSize={{ minRows: 5 }} /></Card>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', color: '#315ead', background: '#eaf1fc' }}><ArrowRightOutlined /></div>
          <Card size="small" title="目标状态"><TextArea value={transition.end_state} onChange={(event) => updateNested('state_transition', { end_state: event.target.value })} placeholder="镜头结束时，必须达到什么可验收状态" autoSize={{ minRows: 5 }} /></Card>
        </div>
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 14 }}>
          {listField('允许发生的变化', transition.allowed_changes, (next) => updateNested('state_transition', { allowed_changes: next }), '例如：柱钢筋按轴线逐根形成\n模板沿作业面依次安装')}
          {listField('禁止跳变', transition.forbidden_jumps, (next) => updateNested('state_transition', { forbidden_jumps: next }), '例如：禁止未绑筋直接浇筑\n禁止已完成构件消失')}
        </div>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 10 }}>
          {frameCards.map(({ label, frame }) => (
            <div key={label} style={{ border: '1px solid #dfe5ed', background: '#fff', overflow: 'hidden' }}>
              {frame?.url ? <img src={frame.url} alt={label} style={{ width: '100%', height: 118, objectFit: 'contain', background: '#eef2f7' }} /> : <div style={{ height: 118, display: 'grid', placeItems: 'center', color: '#8993a5', background: '#f4f6f9' }}>未选择参考帧</div>}
              <div style={{ padding: '8px 10px' }}><Text style={{ fontSize: 11 }}>{label}</Text><Text type="secondary" ellipsis style={{ float: 'right', maxWidth: '58%', fontSize: 11 }}>{frame?.name || '未选择'}</Text></div>
            </div>
          ))}
        </div>
      </div>
    )

    if (activeStep === 3) return (
      <div style={{ display: 'grid', gap: 14 }}>
        <Alert type="info" showIcon message="上下两条时间轴使用同一百分比进度" description={`系统会把 0%–100% 映射到当前 ${duration} 秒视频，分别告诉 Seedance“施工发生什么”和“镜头如何拍”。`} />
        {timelineEditor('construction_timeline', constructionTimeline, '#315ead', '施工状态时间轴')}
        {timelineEditor('camera_timeline', cameraTimeline, '#2f7d5b', '摄影表现时间轴')}
      </div>
    )

    if (activeStep === 4) return (
      <div style={{ display: 'grid', gap: 14 }}>
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 14 }}>
          {listField('空间锚点（全程锁定）', current.spatial_anchors, (next) => update({ spatial_anchors: next }), '例如：主楼外轮廓\n道路与主入口\n塔吊位置', '模型不得移动、增删或改变这些空间关系。')}
          {listField('安全约束', current.safety_constraints, (next) => update({ safety_constraints: next }), '例如：临边防护连续\n人员不进入吊装半径')}
          {listField('必须出现的临时设施', temporary.required, (next) => updateNested('temporary_works', { required: next }), '例如：脚手架\n临边护栏')}
          {listField('禁止出现的临时设施', temporary.forbidden, (next) => updateNested('temporary_works', { forbidden: next }), '例如：错误区域塔吊\n无方案支撑')}
          {listField('质量控制', current.quality_constraints, (next) => update({ quality_constraints: next }), '例如：构件尺寸一致\n节点连接连续')}
          {listField('验收清单', current.acceptance_checks, (next) => update({ acceptance_checks: next }), '例如：构件数量与位置连续\n首尾状态符合目标')}
        </div>
      </div>
    )

    return (
      <div style={{ display: 'grid', gap: 14 }}>
        <Alert
          type={promptOverLimit ? 'error' : promptTooVerbose || frameReviewRisk || !zoneMappings.length ? 'warning' : recipeReady && providerPrompt ? 'success' : 'warning'}
          showIcon
          message={promptOverLimit
            ? '最终提示词超过 Seedance 安全长度'
            : promptTooVerbose
              ? '终稿过长，主施工动作容易被稀释'
              : frameReviewRisk
                ? '首尾帧包含多个连续施工阶段，请确认两帧仍属于同一施工对象'
                : !zoneMappings.length
                  ? '①②③区还没有对应到画面位置'
                  : recipeReady && providerPrompt
                    ? manualOverride ? '人工修订终稿已就绪' : '精简 Seedance 动作指令已生成'
                    : '前五步仍有必填项未完成'}
          description={promptOverLimit
            ? `当前 ${promptLength} 字符，请删减至 2000 字符以内。`
            : promptTooVerbose
              ? `当前 ${promptLength} 字符。施工生成建议控制在 300–800 字；点击“恢复精简自动指令”可重新编译。`
              : frameReviewRisk
                ? '系统仍按首帧到尾帧生成；请确认首帧和尾帧的场地、镜头、主体结构及施工对象一致，时间轴只描述中间动作。'
                : !zoneMappings.length
                  ? '请在“施工单元”填写每个分区在首帧和尾帧中的左/中/右、上/下及可见边界。'
            : recipeReady
              ? manualOverride
                ? '当前为手动修订模式：下方文字会逐字交给 Seedance，完整配方仍保留在同一任务快照中。修改前五步时会自动撤销旧终稿并重新编译。'
                : '完整配方保留在任务快照中；下方是后端去重、去备注并按语义压缩后的实际 Seedance 投喂文本，可直接修改。'
              : '请根据顶部未打勾的步骤补全工程事实、施工单元、状态转换和空间安全约束。'}
        />
        <Card
          size="small"
          title={<Space><Text strong>最终投喂内容</Text><Tag color={manualOverride ? 'orange' : 'green'}>{manualOverride ? '手动修订' : '自动精简'}</Tag><Tag color={promptOverLimit ? 'red' : promptConcise ? 'green' : 'orange'}>{promptLength} 字符</Tag></Space>}
          extra={manualOverride ? <Button size="small" onClick={restoreAutomaticPrompt}>恢复精简自动指令</Button> : undefined}
        >
          <TextArea
            aria-label="最终 Seedance 投喂内容"
            value={providerPrompt}
            onChange={(event) => updateFinalPrompt(event.target.value)}
            placeholder="填写前五步后，系统将在这里生成完整的 Seedance 提示词。"
            autoSize={{ minRows: 14, maxRows: 24 }}
            maxLength={2000}
            showCount
            style={{ lineHeight: 1.75, fontSize: 12, color: '#283548' }}
          />
          <Text type="secondary" style={{ display: 'block', marginTop: 8, fontSize: 11 }}>
            {manualOverride ? '当前内容将原样发送给 Seedance；点击“恢复自动编译”可重新按前五步生成。' : '直接修改即切换为手动修订，刷新页面仍会保存。'}
          </Text>
        </Card>
        <Card size="small" title="生成前质量检查">
          <Space wrap>
            <Tag color={promptConcise ? 'green' : 'orange'}>指令密度：{promptConcise ? '合适' : '需精简'}</Tag>
            <Tag color={zoneMappings.length ? 'green' : 'orange'}>分区定位：{zoneMappings.length ? `${zoneMappings.length} 项` : '未配置'}</Tag>
            <Tag color={frameReviewRisk ? 'orange' : 'green'}>首尾帧核对：{frameReviewRisk ? '需确认同一对象' : '可控'}</Tag>
          </Space>
          {frameReviewRisk && <Text type="secondary" style={{ display: 'block', marginTop: 9, fontSize: 11 }}>这不是阻断条件，首尾帧模式仍可直接生成；建议先核对两张图的空间锚点和施工阶段。</Text>}
        </Card>
        <Card size="small" title="本次生成输入">
          <Space wrap>
            <Tag color={firstFrame ? 'green' : 'red'}>首帧：{firstFrame?.name || '未选择'}</Tag>
            {generationMode === 'first_last_frame_video' && <Tag color={lastFrame ? 'green' : 'red'}>尾帧：{lastFrame?.name || '未选择'}</Tag>}
            {generationMode === 'multi_reference_video' && <Tag color={referenceImages.length >= 2 ? 'green' : 'red'}>参考图：{referenceImages.length} 张</Tag>}
            <Tag>{duration}s</Tag>
            <Tag>Seedance · {modelName || '默认模型'}</Tag>
          </Space>
          {!framesReady && (
            <Alert
              type="warning"
              showIcon
              style={{ marginTop: 10 }}
              message={frameRequirement}
              description={<Button size="small" onClick={onClose}>返回快速生成选择图片</Button>}
            />
          )}
        </Card>
        {negativePrompt && <Text type="secondary" style={{ fontSize: 11 }}>独立负向约束已由后端合并进上面的最终投喂内容。</Text>}
        <Button type="primary" size="large" icon={<SendOutlined />} loading={applyLoading} disabled={!recipeReady || !providerPrompt || promptOverLimit || !framesReady} onClick={() => onApply()}>应用终稿并开始生成</Button>
      </div>
    )
  }

  return (
    <div style={{ color: '#172033', background: '#f4f6f9' }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 16, padding: '16px 20px', background: '#fff', borderBottom: '1px solid #dfe5ed' }}>
        <div style={{ minWidth: 0 }}>
          <Space size={9} wrap>
            <Title level={4} style={{ margin: 0, fontWeight: 600 }}>高级生成 · 施工提示词工程</Title>
            <Tag color="green" icon={<CheckCircleFilled />}>Seedance 单通道</Tag>
            <Tag color="blue">施工演进</Tag>
            <Tag>项目草稿自动保存</Tag>
          </Space>
          <Text type="secondary" style={{ display: 'block', marginTop: 5, fontSize: 12 }}>按工程事实 → 施工顺序 → 双时间轴 → 安全约束生成可审计提示词，再交给 Seedance。</Text>
        </div>
        <Space wrap>
          <Tag>Seedance · {modelName || '默认模型'}</Tag>
          <Button onClick={onClose}>返回快速生成</Button>
          <Button type="primary" icon={<SendOutlined />} disabled={!providerPrompt || promptOverLimit} onClick={() => setActiveStep(5)}>检查最终提示词</Button>
        </Space>
      </div>

      <div role="tablist" aria-label="施工提示词配置步骤" style={{ display: 'grid', gridTemplateColumns: 'repeat(6, minmax(100px, 1fr))', background: '#fff', borderBottom: '1px solid #dfe5ed' }}>
        {stepMeta.map((step, index) => {
          const active = activeStep === index
          return (
            <button
              key={step.title}
              type="button"
              role="tab"
              aria-selected={active}
              onClick={() => setActiveStep(index)}
              style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '12px 13px', border: 0, borderRight: index < 5 ? '1px solid #dfe5ed' : undefined, borderBottom: active ? '3px solid #315ead' : '3px solid transparent', background: active ? '#eaf1fc' : '#fff', color: active ? '#315ead' : '#69758a', cursor: 'pointer', textAlign: 'left' }}
            >
              <span style={{ flex: '0 0 auto', display: 'inline-flex', width: 23, height: 23, alignItems: 'center', justifyContent: 'center', border: `1px solid ${stepDone[index] ? '#2f7d5b' : active ? '#315ead' : '#c5cfdd'}`, borderRadius: '50%', color: stepDone[index] ? '#2f7d5b' : 'inherit', fontSize: 10 }}>{stepDone[index] ? '✓' : String(index + 1).padStart(2, '0')}</span>
              <span><span style={{ display: 'block', fontSize: 12, fontWeight: active ? 600 : 400 }}>{step.title}</span><span style={{ display: 'block', marginTop: 2, fontSize: 9, opacity: 0.78 }}>{step.description}</span></span>
            </button>
          )
        })}
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: '220px minmax(0, 1fr) 270px', minHeight: 620 }}>
        <aside style={{ padding: 16, background: '#fff', borderRight: '1px solid #dfe5ed' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 12 }}><Text strong style={{ fontSize: 13 }}>配方进度</Text><Text type="secondary" style={{ fontSize: 11 }}>V2</Text></div>
          <Progress percent={completion} size="small" strokeColor="#2f7d5b" />
          <Divider style={{ margin: '14px 0' }} />
          <Space direction="vertical" size={8} style={{ width: '100%' }}>
            <Card size="small" styles={{ body: { padding: 10 } }}><Text type="secondary" style={{ fontSize: 10 }}>结构形式</Text><Text strong style={{ display: 'block', marginTop: 3, fontSize: 11 }}>{facts.structure_type || '待填写'}</Text></Card>
            <Card size="small" styles={{ body: { padding: 10 } }}><Text type="secondary" style={{ fontSize: 10 }}>施工单元</Text><Text strong style={{ display: 'block', marginTop: 3, fontSize: 11 }}>{unit.work_item || '待填写'}</Text></Card>
            <Card size="small" styles={{ body: { padding: 10 } }}><Text type="secondary" style={{ fontSize: 10 }}>WBS / 作业区</Text><Text strong style={{ display: 'block', marginTop: 3, fontSize: 11 }}>{unit.wbs_code || '未编码'} · {unit.work_zone || '未定义'}</Text></Card>
          </Space>
          <Divider style={{ margin: '14px 0 10px' }} />
          <Text type="secondary" style={{ fontSize: 11 }}>锁定施工对象</Text>
          <div style={{ marginTop: 8 }}>{asList(unit.objects, ['待定义']).map((item) => <Tag key={item} style={{ margin: '0 5px 5px 0', fontSize: 10 }}>{item}</Tag>)}</div>
        </aside>

        <main style={{ minWidth: 0, padding: 20 }}>
          <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: 16, marginBottom: 16 }}>
            <div><Title level={5} style={{ margin: '0 0 4px' }}>{String(activeStep + 1).padStart(2, '0')} · {stepMeta[activeStep].title}</Title><Text type="secondary" style={{ fontSize: 12 }}>{stepMeta[activeStep].description}</Text></div>
            <Tag color="blue">{duration}s · 施工镜头</Tag>
          </div>
          {renderStep()}
        </main>

        <aside style={{ padding: 16, background: '#fff', borderLeft: '1px solid #dfe5ed' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 12 }}><Text strong style={{ fontSize: 13 }}>实时质检</Text><Tag color={promptOverLimit ? 'red' : 'green'}>{promptOverLimit ? '需精简' : '同步中'}</Tag></div>
          <div style={{ padding: 10, background: '#edf7f2', color: '#2f7d5b', fontSize: 11, lineHeight: 1.6 }}><CheckCircleFilled style={{ marginRight: 6 }} />每次修改都会由后端重新编译，配方与提示词使用同一份任务快照。</div>
          <Divider style={{ margin: '14px 0 10px' }} />
          <Text type="secondary" style={{ fontSize: 11 }}>六步通道</Text>
          <Space direction="vertical" size={7} style={{ width: '100%', marginTop: 9 }}>
            {stepMeta.map((step, index) => <div key={step.title} style={{ display: 'flex', justifyContent: 'space-between', fontSize: 11 }}><Text>{step.title}</Text><Text style={{ color: stepDone[index] ? '#2f7d5b' : '#a95d1b' }}>{stepDone[index] ? '已配置' : '待完善'}</Text></div>)}
          </Space>
          <Divider style={{ margin: '14px 0 10px' }} />
          <Text type="secondary" style={{ fontSize: 11 }}>空间锚点</Text>
          <div style={{ marginTop: 8 }}>{asList(current.spatial_anchors, ['待定义']).map((item) => <Tag key={item} color="blue" icon={<LockOutlined />} style={{ margin: '0 5px 5px 0', fontSize: 10 }}>{item}</Tag>)}</div>
          <div style={{ marginTop: 14, padding: 10, background: '#fff5e9', color: '#a95d1b', fontSize: 11, lineHeight: 1.6 }}><WarningOutlined style={{ marginRight: 5 }} />AI 结果仍需人工对照图纸、专项方案和现场状态复核。</div>
        </aside>
      </div>

      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 12, padding: '12px 18px', borderTop: '1px solid #dfe5ed', background: '#fff' }}>
        <Space><SafetyOutlined style={{ color: '#2f7d5b' }} /><Text type="secondary" style={{ fontSize: 11 }}>前五步可随时返回修改；第六步确认首尾帧和终稿后，可直接创建 Seedance 生成任务。</Text></Space>
        <Space>
          <Button icon={<ArrowLeftOutlined />} disabled={activeStep === 0} onClick={() => setActiveStep((step) => step - 1)}>上一步</Button>
          {activeStep < 5
            ? <Button type="primary" icon={<ArrowRightOutlined />} onClick={() => setActiveStep((step) => step + 1)}>保存并下一步</Button>
            : <Button type="primary" icon={<SendOutlined />} loading={applyLoading} disabled={!recipeReady || !providerPrompt || promptOverLimit || !framesReady} onClick={() => onApply()}>应用终稿并开始生成</Button>}
        </Space>
      </div>
    </div>
  )
}

export default function ConstructionWorkbenchModal(props: ConstructionWorkbenchModalProps) {
  return (
    <Modal
      open={props.open}
      onCancel={props.onClose}
      width="min(1460px, calc(100vw - 32px))"
      footer={null}
      destroyOnClose={false}
      styles={{ body: { padding: 0, background: '#f4f6f9' } }}
      title={null}
    >
      <ConstructionWorkbenchContent {...props} />
    </Modal>
  )
}
