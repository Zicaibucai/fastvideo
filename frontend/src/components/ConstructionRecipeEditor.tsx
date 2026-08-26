import { useMemo } from 'react'
import {
  Alert,
  Collapse,
  Divider,
  Input,
  InputNumber,
  Select,
  Space,
  Tag,
  Typography,
} from 'antd'

const { Text } = Typography

export type ConstructionRecipe = Record<string, any>

type TimelineRow = { from: number; to: number; instruction: string }

interface ConstructionRecipeEditorProps {
  value: ConstructionRecipe | null | undefined
  onChange: (next: ConstructionRecipe) => void
  compact?: boolean
  defaultOpen?: boolean
}

const DEFAULT_TIMELINE: TimelineRow[] = [
  { from: 0, to: 20, instruction: '确认前置条件与作业面，保持已完成构件和安全设施稳定' },
  { from: 20, to: 80, instruction: '按照声明的施工顺序推进一个主工序，不跨越未声明的状态' },
  { from: 80, to: 100, instruction: '完成目标状态，停止结构变化并保持画面连续定格' },
]

const DEFAULT_CAMERA_TIMELINE: TimelineRow[] = [
  { from: 0, to: 20, instruction: '固定机位建立全景，交代作业区、机械和空间锚点' },
  { from: 20, to: 80, instruction: '保持轴线和焦段稳定，缓慢跟随施工工作面' },
  { from: 80, to: 100, instruction: '减速并定格在目标完成状态，不切镜' },
]

const listValue = (value: any) => Array.isArray(value) ? value.join('\n') : String(value || '')
const parseList = (value: string) => value.split(/[\n；;]+/).map((item) => item.trim()).filter(Boolean).slice(0, 12)

const normalized = (value: ConstructionRecipe | null | undefined): ConstructionRecipe => {
  const source = value && typeof value === 'object' ? value : {}
  const projectFacts = source.project_facts && typeof source.project_facts === 'object' ? source.project_facts : {}
  const constructionUnit = source.construction_unit && typeof source.construction_unit === 'object' ? source.construction_unit : {}
  const transition = source.state_transition && typeof source.state_transition === 'object' ? source.state_transition : {}
  const temporary = source.temporary_works && typeof source.temporary_works === 'object' ? source.temporary_works : {}
  const timeline = Array.isArray(source.construction_timeline) && source.construction_timeline.length ? source.construction_timeline : DEFAULT_TIMELINE
  const cameraTimeline = Array.isArray(source.camera_timeline) && source.camera_timeline.length ? source.camera_timeline : DEFAULT_CAMERA_TIMELINE
  return {
    ...source,
    recipe_version: Math.max(2, Number(source.recipe_version || 2)),
    construction_mode: source.construction_mode === 'construction_evolution' ? 'construction_evolution' : 'presentation',
    project_facts: {
      structure_type: String(projectFacts.structure_type || ''),
      current_stage: String(projectFacts.current_stage || ''),
      target_stage: String(projectFacts.target_stage || ''),
      fact_sources: Array.isArray(projectFacts.fact_sources) ? projectFacts.fact_sources : [],
    },
    construction_unit: {
      wbs_code: String(constructionUnit.wbs_code || ''),
      work_item: String(constructionUnit.work_item || ''),
      work_zone: String(constructionUnit.work_zone || ''),
      objects: Array.isArray(constructionUnit.objects) ? constructionUnit.objects : [],
      prerequisites: Array.isArray(constructionUnit.prerequisites) ? constructionUnit.prerequisites : [],
      completion_state: Array.isArray(constructionUnit.completion_state) ? constructionUnit.completion_state : [],
    },
    state_transition: {
      start_state: String(transition.start_state || ''),
      end_state: String(transition.end_state || ''),
      allowed_changes: Array.isArray(transition.allowed_changes) ? transition.allowed_changes : [],
      forbidden_jumps: Array.isArray(transition.forbidden_jumps) ? transition.forbidden_jumps : [],
    },
    construction_timeline: timeline,
    camera_timeline: cameraTimeline,
    spatial_anchors: Array.isArray(source.spatial_anchors) ? source.spatial_anchors : [],
    temporary_works: {
      required: Array.isArray(temporary.required) ? temporary.required : [],
      forbidden: Array.isArray(temporary.forbidden) ? temporary.forbidden : [],
    },
    safety_constraints: Array.isArray(source.safety_constraints) ? source.safety_constraints : [],
    quality_constraints: Array.isArray(source.quality_constraints) ? source.quality_constraints : [],
    acceptance_checks: Array.isArray(source.acceptance_checks) ? source.acceptance_checks : [],
  }
}

export default function ConstructionRecipeEditor({ value, onChange, compact = false, defaultOpen = true }: ConstructionRecipeEditorProps) {
  const recipe = useMemo(() => normalized(value), [value])
  const update = (patch: ConstructionRecipe) => onChange({ ...recipe, ...patch })
  const updateNested = (key: string, patch: ConstructionRecipe) => update({ [key]: { ...(recipe[key] || {}), ...patch } })

  const updateTimeline = (key: 'construction_timeline' | 'camera_timeline', index: number, patch: Partial<TimelineRow>) => {
    const rows = (recipe[key] as TimelineRow[]).map((row, rowIndex) => rowIndex === index ? { ...row, ...patch } : row)
    update({ [key]: rows })
  }

  const timelineEditor = (title: string, key: 'construction_timeline' | 'camera_timeline') => (
    <div style={{ marginTop: 10 }}>
      <Text type="secondary" style={{ fontSize: 12 }}>{title}</Text>
      <Space direction="vertical" size={6} style={{ width: '100%', marginTop: 6 }}>
        {(recipe[key] as TimelineRow[]).map((row, index) => (
          <div key={`${key}-${index}`} style={{ display: 'grid', gridTemplateColumns: '54px 54px minmax(0, 1fr)', gap: 6 }}>
            <InputNumber size="small" min={0} max={100} value={row.from} addonAfter="%" onChange={(from) => updateTimeline(key, index, { from: Number(from ?? row.from) })} />
            <InputNumber size="small" min={0} max={100} value={row.to} addonAfter="%" onChange={(to) => updateTimeline(key, index, { to: Number(to ?? row.to) })} />
            <Input size="small" value={row.instruction} onChange={(event) => updateTimeline(key, index, { instruction: event.target.value })} />
          </div>
        ))}
      </Space>
    </div>
  )

  const listEditor = (label: string, key: string, nestedKey?: string) => {
    const current = nestedKey ? recipe[key]?.[nestedKey] : recipe[key]
    const setValue = (text: string) => nestedKey
      ? updateNested(key, { [nestedKey]: parseList(text) })
      : update({ [key]: parseList(text) })
    return (
      <div>
        <Text type="secondary" style={{ fontSize: 12 }}>{label}</Text>
        <Input.TextArea
          rows={compact ? 2 : 3}
          value={listValue(current)}
          onChange={(event) => setValue(event.target.value)}
          placeholder="每行一项"
          style={{ marginTop: 5, fontSize: 12, resize: 'vertical' }}
        />
      </div>
    )
  }

  return (
    <Collapse
      defaultActiveKey={defaultOpen ? ['construction'] : []}
      items={[{
        key: 'construction',
        label: <Space size={8}><Text strong>施工配方 V2</Text><Tag color="blue">自动投喂 Seedance</Tag></Space>,
        children: (
          <Space direction="vertical" size={12} style={{ width: '100%' }}>
            <Alert
              type="info"
              showIcon
              message="这里的字段会由后端统一编译为最终 Seedance 提示词，并保存到任务快照。"
              description="施工演进模式允许声明范围内的构件逐步形成；建筑展示模式继续锁定主体结构。"
            />
            <div style={{ display: 'grid', gridTemplateColumns: compact ? '1fr' : '1fr 1fr', gap: 10 }}>
              <div><Text type="secondary" style={{ fontSize: 12 }}>施工模式</Text><Select size="small" style={{ width: '100%', marginTop: 5 }} value={recipe.construction_mode} onChange={(construction_mode) => update({ construction_mode })} options={[{ value: 'presentation', label: '建筑展示（结构锁定）' }, { value: 'construction_evolution', label: '施工演进（受控变化）' }]} /></div>
              <div><Text type="secondary" style={{ fontSize: 12 }}>WBS 编码</Text><Input size="small" style={{ marginTop: 5 }} value={recipe.construction_unit.wbs_code} onChange={(event) => updateNested('construction_unit', { wbs_code: event.target.value })} placeholder="例如 03.02.04" /></div>
            </div>
            <Divider style={{ margin: '2px 0' }} />
            <div style={{ display: 'grid', gridTemplateColumns: compact ? '1fr' : '1fr 1fr', gap: 10 }}>
              <div><Text type="secondary" style={{ fontSize: 12 }}>结构形式</Text><Input size="small" style={{ marginTop: 5 }} value={recipe.project_facts.structure_type} onChange={(event) => updateNested('project_facts', { structure_type: event.target.value })} placeholder="钢筋混凝土框架-核心筒" /></div>
              <div><Text type="secondary" style={{ fontSize: 12 }}>作业项</Text><Input size="small" style={{ marginTop: 5 }} value={recipe.construction_unit.work_item} onChange={(event) => updateNested('construction_unit', { work_item: event.target.value })} placeholder="地下室底板混凝土浇筑" /></div>
              <div><Text type="secondary" style={{ fontSize: 12 }}>当前施工阶段</Text><Input size="small" style={{ marginTop: 5 }} value={recipe.project_facts.current_stage} onChange={(event) => updateNested('project_facts', { current_stage: event.target.value })} /></div>
              <div><Text type="secondary" style={{ fontSize: 12 }}>作业区</Text><Input size="small" style={{ marginTop: 5 }} value={recipe.construction_unit.work_zone} onChange={(event) => updateNested('construction_unit', { work_zone: event.target.value })} placeholder="A 区 / 轴线 1-8" /></div>
            </div>
            <div style={{ display: 'grid', gridTemplateColumns: compact ? '1fr' : '1fr 1fr', gap: 10 }}>
              <div><Text type="secondary" style={{ fontSize: 12 }}>开始状态</Text><Input.TextArea rows={compact ? 2 : 3} value={recipe.state_transition.start_state} onChange={(event) => updateNested('state_transition', { start_state: event.target.value })} style={{ marginTop: 5, fontSize: 12 }} /></div>
              <div><Text type="secondary" style={{ fontSize: 12 }}>目标状态</Text><Input.TextArea rows={compact ? 2 : 3} value={recipe.state_transition.end_state} onChange={(event) => updateNested('state_transition', { end_state: event.target.value })} style={{ marginTop: 5, fontSize: 12 }} /></div>
            </div>
            {timelineEditor('施工时间轴（工程状态）', 'construction_timeline')}
            {timelineEditor('摄影时间轴（镜头表现）', 'camera_timeline')}
            <div style={{ display: 'grid', gridTemplateColumns: compact ? '1fr' : '1fr 1fr', gap: 10 }}>
              {listEditor('施工对象', 'construction_unit', 'objects')}
              {listEditor('前置条件', 'construction_unit', 'prerequisites')}
              {listEditor('完成标志', 'construction_unit', 'completion_state')}
              {listEditor('允许变化（受控）', 'state_transition', 'allowed_changes')}
              {listEditor('禁止跳变', 'state_transition', 'forbidden_jumps')}
              {listEditor('空间锚点（必须锁定）', 'spatial_anchors')}
              {listEditor('必须出现的临时设施', 'temporary_works', 'required')}
              {listEditor('禁止出现的临时设施', 'temporary_works', 'forbidden')}
              {listEditor('安全约束', 'safety_constraints')}
              {listEditor('质量约束', 'quality_constraints')}
              {listEditor('验收清单', 'acceptance_checks')}
            </div>
          </Space>
        ),
      }]}
    />
  )
}
