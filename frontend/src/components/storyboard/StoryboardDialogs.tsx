import { Button, Card, Col, Descriptions, Empty, Form, Input, InputNumber, List, Modal, Row, Select, Space, Switch, Tag, Typography } from 'antd'
import type { StoryboardShot } from '../../api/types'
import { FACT_STATUS_MAP, SECTION_OPTIONS, VISUAL_TYPES } from '../../features/storyboard/constants'

const { Text, Paragraph } = Typography

export interface StoryboardDialogProps {
  [key: string]: any
}

/** 分镜编辑相关弹窗集合；页面本身只负责数据加载和事件编排。 */
export default function StoryboardDialogs(props: StoryboardDialogProps) {
  const {
    resegmentModalOpen, handleResegmentSubmit, setResegmentModalOpen, generating, resegmentForm,
    genModalOpen, handleGenerateSubmit, setGenModalOpen, genForm,
    evidenceModalOpen, setEvidenceModalOpen, evidenceRun, handleApproveEvidence,
    addModalOpen, handleAddSubmit, setAddModalOpen, addForm, shots,
    editShot, handleSaveEdit, setEditShot, editForm,
    historyShot, setHistoryShot, handleRestore,
  } = props

  return <>
    <Modal title="AI 重新调整分镜" open={resegmentModalOpen} onOk={handleResegmentSubmit} onCancel={() => setResegmentModalOpen(false)} okText="开始调整" confirmLoading={generating} width={560}>
      <Text type="secondary" style={{ display: 'block', marginBottom: 16 }}>正文保持不变，只重新划分镜头边界、章节标题和画面组织。已有画面素材会尽量保留。</Text>
      <Form form={resegmentForm} layout="vertical">
        <Form.Item name="target_shot_count" label="目标分镜数量" rules={[{ required: true, message: '请输入目标分镜数量' }]}><InputNumber min={1} max={100} style={{ width: '100%' }} /></Form.Item>
        <Form.Item name="chars_per_minute" label="参考语速（字/分钟）"><InputNumber min={120} max={400} style={{ width: '100%' }} /></Form.Item>
        <Form.Item name="instructions" label="调整要求"><Input.TextArea rows={4} placeholder="例如：项目概况集中在前两镜，主体结构按施工顺序拆开，机电穿插单独成章。" /></Form.Item>
      </Form>
    </Modal>

    <Modal title="智能拆解解说词" open={genModalOpen} onOk={handleGenerateSubmit} onCancel={() => setGenModalOpen(false)} okText="开始生成" confirmLoading={generating} width={560}>
      <Text type="secondary" style={{ display: 'block', marginBottom: 16 }}>将先核对资料，再编排章节、分章写作并复核事实。未能核实的内容不会写成确定结论。</Text>
      <Form form={genForm} layout="vertical">
        <Form.Item name="predefined_outline" label="预设解说词大纲" extra="可选。填写后AI按你的顺序整理证据、编排章节和写稿；留空则根据标书原文标题、证据分布和施工逻辑自动提炼，不限定章节数量。"><Input.TextArea rows={8} placeholder={'可留空自动提炼；或填写：\n1. 项目概况与总体部署\n2. 基坑土方与基础施工\n3. 主体结构与专业穿插'} /></Form.Item>
        <Row gutter={12}><Col span={12}><Form.Item name="target_duration_seconds" label="视频目标时长（秒）"><InputNumber min={60} max={1800} style={{ width: '100%' }} /></Form.Item></Col><Col span={12}><Form.Item name="section_count" label="分镜数量"><InputNumber min={8} max={100} style={{ width: '100%' }} /></Form.Item></Col></Row>
        <Form.Item name="tone" label="解说风格"><Select options={['专业庄重', '科技感', '简洁明快', '宏大叙事'].map((t) => ({ label: t, value: t }))} /></Form.Item>
        <Form.Item name="video_purpose" label="视频用途"><Select options={['投标答辩', '企业宣传', '评审汇报', '项目汇报'].map((t) => ({ label: t, value: t }))} /></Form.Item>
        <Form.Item name="chars_per_minute" label="每分钟参考字数"><InputNumber min={120} max={400} style={{ width: '100%' }} /></Form.Item>
        <Row gutter={12}><Col span={12}><Form.Item name="target_beat_count" label="旁白短句数量"><InputNumber min={20} max={240} style={{ width: '100%' }} /></Form.Item></Col><Col span={12}><Form.Item name="evidence_batch_chars" label="全文批次大小"><InputNumber min={3000} max={16000} step={500} style={{ width: '100%' }} /></Form.Item></Col></Row>
        <Form.Item name="evidence_concurrency" label="证据批次并发数"><InputNumber min={1} max={8} style={{ width: '100%' }} /></Form.Item>
        <Form.Item name="custom_requirements" label="额外要求"><Input.TextArea rows={3} placeholder="例如：重点展开土方开挖、塔吊布置与机电穿插；结尾控制在 20 秒内" /></Form.Item>
        <Row gutter={12}><Col span={12}><Form.Item name="include_company_intro" label="包含企业介绍" valuePropName="checked"><Switch /></Form.Item></Col><Col span={12}><Form.Item name="include_construction_simulation" label="包含施工推演" valuePropName="checked"><Switch /></Form.Item></Col></Row>
        <Row gutter={12}><Col span={12}><Form.Item name="evidence_auto_approve" label="自动通过证据" valuePropName="checked"><Switch /></Form.Item></Col><Col span={12}><Form.Item name="strict_fact_mode" label="严格事实模式" valuePropName="checked"><Switch /></Form.Item></Col></Row>
      </Form>
    </Modal>

    <Modal title="全文证据审核" open={evidenceModalOpen} onCancel={() => setEvidenceModalOpen(false)} footer={[<Button key="close" onClick={() => setEvidenceModalOpen(false)}>关闭</Button>, <Button key="approve" type="primary" onClick={handleApproveEvidence}>通过并继续生成</Button>]} width={760}>
      {evidenceRun && <><Descriptions size="small" column={3} bordered><Descriptions.Item label="运行状态">{evidenceRun.run?.status}</Descriptions.Item><Descriptions.Item label="批次进度">{evidenceRun.run?.completed_batches}/{evidenceRun.run?.total_batches}</Descriptions.Item><Descriptions.Item label="证据条数">{evidenceRun.run?.evidence_count}</Descriptions.Item></Descriptions><List size="small" dataSource={(evidenceRun.evidence || []).slice(0, 80)} renderItem={(item: any) => <List.Item><Space direction="vertical" size={2} style={{ width: '100%' }}><Space wrap><Tag color="blue">{item.topic}</Tag><Tag>{item.fact_check_status}</Tag><Text type="secondary">{item.source_reference?.documentName || '来源文件'} {item.source_reference?.page ? `P${item.source_reference.page}` : item.source_reference?.locationLabel || ''}</Text></Space><Text>{item.fact}</Text></Space></List.Item>} /></>}
    </Modal>

    <Modal title="添加分镜" open={addModalOpen} onOk={handleAddSubmit} onCancel={() => setAddModalOpen(false)} okText="添加" width={640}>
      <Form form={addForm} layout="vertical">
        <Row gutter={12}><Col span={12}><Form.Item name="insert_at" label="插入位置" rules={[{ required: true, message: '请选择插入位置' }]}><InputNumber min={1} max={shots.length + 1} style={{ width: '100%' }} /></Form.Item></Col><Col span={12}><Form.Item name="duration_seconds" label="预计时长（秒）" rules={[{ required: true, message: '请输入时长' }]}><InputNumber min={1} max={120} style={{ width: '100%' }} /></Form.Item></Col></Row>
        <Form.Item name="title" label="分镜标题" rules={[{ required: true, message: '请输入标题' }]}><Input placeholder="例如：地下室结构施工" /></Form.Item>
        <Form.Item name="section" label="章节"><Select options={SECTION_OPTIONS.map((s) => ({ label: s, value: s }))} /></Form.Item>
        <Form.Item name="narration" label="解说词" rules={[{ required: true, message: '请输入解说词' }]}><Input.TextArea rows={4} placeholder="写清施工对象、作业顺序和控制要点" /></Form.Item>
        <Row gutter={12}><Col span={12}><Form.Item name="visual_type" label="画面类型"><Select options={VISUAL_TYPES} /></Form.Item></Col><Col span={12}><Form.Item name="fact_check_status" label="事实状态"><Select options={Object.entries(FACT_STATUS_MAP).map(([k, v]) => ({ label: v.label, value: k }))} /></Form.Item></Col></Row>
        <Form.Item name="visual_description" label="画面描述"><Input.TextArea rows={2} placeholder="例如：BIM 展示地下室分区、流水方向与吊装路线" /></Form.Item>
      </Form>
    </Modal>

    <Modal title={`编辑分镜 #${editShot?.sequence || ''}`} open={!!editShot} onOk={handleSaveEdit} onCancel={() => setEditShot(null)} width={640}>
      <Form form={editForm} layout="vertical"><Form.Item name="title" label="分镜标题"><Input /></Form.Item><Form.Item name="section" label="章节"><Select options={SECTION_OPTIONS.map((s) => ({ label: s, value: s }))} allowClear /></Form.Item><Form.Item name="narration" label="解说词" rules={[{ required: true, message: '请输入解说词' }]}><Input.TextArea rows={4} /></Form.Item><Row gutter={12}><Col span={12}><Form.Item name="visual_type" label="画面类型"><Select options={VISUAL_TYPES} allowClear /></Form.Item></Col><Col span={12}><Form.Item name="duration_seconds" label="预计时长（秒）"><InputNumber min={1} max={120} style={{ width: '100%' }} /></Form.Item></Col></Row><Form.Item name="visual_description" label="画面描述"><Input.TextArea rows={2} /></Form.Item><Form.Item name="source_page" label="来源页码（招标文件）"><InputNumber min={1} style={{ width: '100%' }} placeholder="可选" /></Form.Item><Form.Item name="fact_check_status" label="事实校验状态"><Select options={Object.entries(FACT_STATUS_MAP).map(([k, v]) => ({ label: v.label, value: k }))} allowClear /></Form.Item></Form>
    </Modal>

    <Modal title={`历史版本 - ${historyShot?.title || '分镜'}`} open={!!historyShot} onCancel={() => setHistoryShot(null)} footer={null} width={680}>
      {(historyShot?.versions || []).length === 0 && <Empty description="暂无历史版本" />}
      {historyShot?.versions?.map((version: any) => <Card key={version.revision} size="small" style={{ marginBottom: 8 }}><Space direction="vertical" style={{ width: '100%' }}><Space><Tag color={version.source === 'ai' ? 'blue' : 'green'}>版本 {version.revision} · {version.source === 'ai' ? 'AI生成' : '人工编辑'}</Tag><Text type="secondary" style={{ fontSize: 12 }}>{version.created_at}</Text></Space><Paragraph style={{ marginBottom: 0 }}>{version.narration}</Paragraph>{version.visual_prompt && <Text type="secondary" style={{ fontSize: 12 }}>画面提示词：{version.visual_prompt}</Text>}<Button size="small" type="primary" ghost onClick={() => handleRestore(historyShot, version.revision)}>恢复此版本</Button></Space></Card>)}
    </Modal>
  </>
}
