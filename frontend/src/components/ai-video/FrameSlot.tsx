import { useState } from 'react'
import { Button, Modal, Select, Space, Typography, Upload } from 'antd'
import { ClearOutlined, UploadOutlined } from '@ant-design/icons'
import type { ReferenceImage } from '../../api/types'
import { formatImageDimensions } from '../../pages/aiVideoUtils'

const { Text } = Typography

export interface FrameSlotProps {
  label: string
  frame: ReferenceImage | null
  images: ReferenceImage[]
  onSelect: (id: string) => void
  onClear: () => void
  onUpload: (file: File) => void
}

/** 首/尾帧选择器：把素材选择、上传和预览的 UI 状态封装在组件内部。 */
export default function FrameSlot({ label, frame, images, onSelect, onClear, onUpload }: FrameSlotProps) {
  const [previewOpen, setPreviewOpen] = useState(false)

  return (
    <div style={{ flex: 1, minWidth: 0 }}>
      <Text strong style={{ fontSize: 12, color: '#475569' }}>{label}</Text>
      <div style={{ marginTop: 6, position: 'relative', height: 178, borderRadius: 8, border: '1px dashed #d9d9d9', overflow: 'hidden', background: '#F8FAFC' }}>
        {frame ? (
          <>
            <button type="button" onClick={() => setPreviewOpen(true)} style={{ width: '100%', height: '100%', padding: 0, border: 0, background: '#eef2f7', cursor: 'zoom-in' }}>
              <img src={frame.url} alt={frame.name} style={{ width: '100%', height: '100%', objectFit: 'contain', display: 'block' }} />
            </button>
            <Button aria-label={`清除${label}`} size="small" icon={<ClearOutlined />} style={{ position: 'absolute', top: 6, right: 6 }} onClick={onClear} />
          </>
        ) : (
          <div style={{ width: '100%', height: '100%', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
            <Text type="secondary" style={{ fontSize: 12 }}>未选择{label}</Text>
          </div>
        )}
      </div>
      {frame && <div style={{ marginTop: 6, minHeight: 36 }}>
        <Text strong ellipsis={{ tooltip: frame.name }} style={{ display: 'block', fontSize: 12 }}>{frame.name}</Text>
        <Text type="secondary" style={{ fontSize: 11 }}>
          {formatImageDimensions(frame.width, frame.height) && `${formatImageDimensions(frame.width, frame.height)} · `}
          {frame.source || '素材库'}
        </Text>
      </div>}
      <Space style={{ marginTop: 6, width: '100%' }}>
        <Select
          aria-label={`${label}素材选择`}
          size="small"
          style={{ flex: 1, minWidth: 0 }}
          placeholder="选择素材"
          value={frame?.id}
          onChange={onSelect}
          showSearch
          optionFilterProp="label"
          dropdownMatchSelectWidth={false}
          dropdownStyle={{ minWidth: 320 }}
          options={images.map((i) => ({ value: i.id, label: i.name, image: i }))}
          optionRender={(option) => {
            const image = (option.data as { image?: ReferenceImage }).image
            const dimensions = formatImageDimensions(image?.width, image?.height)
            return <Space style={{ width: '100%' }}><img src={image?.url} alt="" style={{ width: 52, height: 38, objectFit: 'contain', background: '#eef2f7', borderRadius: 4 }} /><span style={{ minWidth: 0 }}><Text ellipsis={{ tooltip: option.label as string }} style={{ display: 'block', maxWidth: 220 }}>{option.label}</Text>{dimensions && <Text type="secondary" style={{ fontSize: 11 }}>{dimensions}</Text>}</span></Space>
          }}
        />
        <Upload accept=".jpg,.jpeg,.png,.webp" showUploadList={false} beforeUpload={(file) => { onUpload(file); return false }}>
          <Button size="small" icon={<UploadOutlined />}>上传</Button>
        </Upload>
      </Space>
      <Modal open={previewOpen} title={frame?.name || label} footer={null} onCancel={() => setPreviewOpen(false)} width={760} centered>
        {frame && <img src={frame.url} alt={frame.name} style={{ width: '100%', maxHeight: '70vh', objectFit: 'contain', background: '#f3f5f8' }} />}
      </Modal>
    </div>
  )
}
