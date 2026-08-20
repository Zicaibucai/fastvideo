import { useEffect, useState } from 'react'
import {
  Modal,
  Table,
  Button,
  Space,
  Input,
  Select,
  InputNumber,
  Form,
  Popconfirm,
  Alert,
  Tag,
  Upload,
  App,
} from 'antd'
import { PlusOutlined, DeleteOutlined, ExportOutlined, ImportOutlined, ExperimentOutlined } from '@ant-design/icons'
import { pronunciationApi } from '../api'
import type { PronunciationRule } from '../api/types'

const RULE_TYPES = [
  { label: '字面替换', value: 'literal' },
  { label: '数字/单位', value: 'number' },
  { label: '单位', value: 'unit' },
  { label: '缩写', value: 'abbreviation' },
  { label: '企业名称', value: 'company' },
  { label: '自定义', value: 'custom' },
]

export default function PronunciationModal({
  open,
  projectId,
  onClose,
}: {
  open: boolean
  projectId: string
  onClose: () => void
}) {
  const { message } = App.useApp()
  const [rules, setRules] = useState<PronunciationRule[]>([])
  const [form] = Form.useForm()
  const [testText, setTestText] = useState('')
  const [testResult, setTestResult] = useState<{ normalized_text: string; warnings: string[] } | null>(null)
  const [editing, setEditing] = useState<PronunciationRule | null>(null)

  const fetchRules = () => {
    pronunciationApi.list(projectId).then((res) => setRules(res.data)).catch(() => {})
  }

  useEffect(() => {
    if (open) {
      fetchRules()
      setTestResult(null)
    }
  }, [open, projectId])

  const handleCreate = async () => {
    const values = await form.validateFields().catch(() => null)
    if (!values) return
    try {
      await pronunciationApi.create(projectId, values)
      message.success('规则已创建')
      form.resetFields()
      fetchRules()
    } catch {
      // 已提示
    }
  }

  const handleUpdate = async () => {
    if (!editing) return
    const values = await form.validateFields().catch(() => null)
    if (!values) return
    try {
      await pronunciationApi.update(projectId, editing.id, values)
      message.success('规则已更新')
      setEditing(null)
      form.resetFields()
      fetchRules()
    } catch {
      // 已提示
    }
  }

  const handleDelete = async (id: string) => {
    try {
      await pronunciationApi.remove(projectId, id)
      message.success('规则已删除')
      fetchRules()
    } catch {
      // 已提示
    }
  }

  const handleTest = async () => {
    if (!testText.trim()) {
      message.warning('请输入要测试的文本')
      return
    }
    try {
      const res = await pronunciationApi.test(projectId, testText)
      setTestResult({ normalized_text: res.data.normalized_text, warnings: res.data.warnings })
    } catch {
      // 已提示
    }
  }

  const handleImport = async (file: File) => {
    try {
      const text = await file.text()
      const data = JSON.parse(text)
      const rulesList = Array.isArray(data) ? data : data.rules
      const res = await pronunciationApi.importJson(projectId, rulesList || [])
      message.success(`导入完成：新建 ${res.data.created || 0} 条`)
      fetchRules()
    } catch (e) {
      message.error('导入失败：JSON 格式错误')
    }
    return false
  }

  const handleExport = async () => {
    try {
      const res = await pronunciationApi.exportJson(projectId)
      const blob = new Blob([JSON.stringify(res.data, null, 2)], { type: 'application/json' })
      const link = document.createElement('a')
      link.href = URL.createObjectURL(blob)
      link.download = 'pronunciation_rules.json'
      link.click()
      URL.revokeObjectURL(link.href)
    } catch {
      // 已提示
    }
  }

  const editRule = (rule: PronunciationRule) => {
    setEditing(rule)
    form.setFieldsValue({
      source_text: rule.source_text,
      spoken_text: rule.spoken_text,
      rule_type: rule.rule_type,
      priority: rule.priority,
      is_regex: rule.is_regex,
    })
  }

  return (
    <Modal title="发音词典" open={open} onCancel={onClose} footer={null} width={760}>
      <Alert
        type="info"
        showIcon
        style={{ marginBottom: 12 }}
        message="发音词典把解说词中的数字、单位、缩写、企业名称转换为准确朗读文本，不影响原始解说词。项目词典优先级最高。"
      />
      <Space style={{ marginBottom: 8 }}>
        <Button size="small" icon={<ExportOutlined />} onClick={handleExport}>导出 JSON</Button>
        <Upload accept=".json" showUploadList={false} beforeUpload={(f) => handleImport(f)}>
          <Button size="small" icon={<ImportOutlined />}>导入 JSON</Button>
        </Upload>
      </Space>

      <Table
        size="small"
        rowKey="id"
        dataSource={rules}
        pagination={false}
        style={{ marginBottom: 12 }}
        columns={[
          { title: '源文本', dataIndex: 'source_text', width: 120, ellipsis: true },
          { title: '朗读文本', dataIndex: 'spoken_text', width: 140, ellipsis: true },
          { title: '类型', dataIndex: 'rule_type', width: 80 },
          { title: '优先级', dataIndex: 'priority', width: 70 },
          { title: '范围', dataIndex: 'scope', width: 70, render: (v) => <Tag>{v}</Tag> },
          { title: '状态', dataIndex: 'enabled', width: 60, render: (v) => (v ? '启用' : '停用') },
          {
            title: '操作',
            width: 90,
            render: (_, r) => (
              <Space size={4}>
                <Button size="small" onClick={() => editRule(r)}>编辑</Button>
                {r.scope !== 'system' && (
                  <Popconfirm title="删除该规则？" onConfirm={() => handleDelete(r.id)}>
                    <Button size="small" danger icon={<DeleteOutlined />} />
                  </Popconfirm>
                )}
              </Space>
            ),
          },
        ]}
      />

      <Form form={form} layout="inline" style={{ rowGap: 8 }} initialValues={{ rule_type: 'literal', priority: 100, is_regex: false }}>
        <Form.Item label="源文本" name="source_text" rules={[{ required: true, message: '必填' }]}>
          <Input style={{ width: 140 }} placeholder="如：C40" />
        </Form.Item>
        <Form.Item label="朗读" name="spoken_text" rules={[{ required: true, message: '必填' }]}>
          <Input style={{ width: 140 }} placeholder="如：C四零" />
        </Form.Item>
        <Form.Item label="类型" name="rule_type">
          <Select style={{ width: 110 }} options={RULE_TYPES} />
        </Form.Item>
        <Form.Item label="优先级" name="priority">
          <InputNumber min={1} max={999} style={{ width: 80 }} />
        </Form.Item>
        <Form.Item>
          <Space>
            {editing ? (
              <Button type="primary" onClick={handleUpdate}>保存修改</Button>
            ) : (
              <Button type="primary" icon={<PlusOutlined />} onClick={handleCreate}>添加规则</Button>
            )}
          </Space>
        </Form.Item>
      </Form>

      <DividerSpacing />
      <b>朗读测试</b>
      <Space.Compact style={{ width: '100%', marginTop: 4 }}>
        <Input
          value={testText}
          onChange={(e) => setTestText(e.target.value)}
          placeholder="输入解说词片段测试朗读效果，如：C40混凝土 8.5MPa 2026年3月1日"
        />
        <Button type="primary" icon={<ExperimentOutlined />} onClick={handleTest}>测试</Button>
      </Space.Compact>
      {testResult && (
        <div style={{ marginTop: 8, background: '#fafafa', padding: 8, borderRadius: 6 }}>
          <div><b>朗读文本：</b>{testResult.normalized_text}</div>
          {testResult.warnings.length > 0 && (
            <Alert type="warning" showIcon style={{ marginTop: 4 }} message={testResult.warnings.join('；')} />
          )}
        </div>
      )}
    </Modal>
  )
}

function DividerSpacing() {
  return <div style={{ height: 16 }} />
}
