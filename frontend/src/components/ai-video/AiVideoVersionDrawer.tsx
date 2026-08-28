import { Button, Card, Drawer, Empty, Space, Tag, Typography } from 'antd'
import { CheckOutlined, DeleteOutlined, DownloadOutlined, EditOutlined } from '@ant-design/icons'
import { downloadAiVideo } from '../../api'
import { PROVIDER_LABELS, versionDisplayName, versionDownloadName } from '../../pages/aiVideoUtils'

const { Text } = Typography

export interface AiVideoVersionDrawerProps {
  [key: string]: any
}

/** 生成结果版本中心：只处理版本展示和用户操作回调。 */
export default function AiVideoVersionDrawer({ drawerOpen, setDrawerOpen, versions, openRenameVersion, handleSelectVersion, handleDeleteVersion }: AiVideoVersionDrawerProps) {
  return <Drawer title="视频结果版本" placement="right" width={440} open={drawerOpen} onClose={() => setDrawerOpen(false)}>
    {versions.length === 0 && <Empty description="暂无结果版本" style={{ marginTop: 12 }} />}
    <div style={{ marginTop: 8, display: 'flex', flexDirection: 'column', gap: 8 }}>
      {versions.map((version: any) => <Card key={version.id} size="small">
        <div style={{ position: 'relative' }}>
          {version.result_url ? <video src={version.result_url} style={{ width: '100%', height: 140, objectFit: 'cover', borderRadius: 4, background: '#000' }} controls preload="metadata" /> : <div style={{ width: '100%', height: 140, background: '#f5f5f5', display: 'flex', alignItems: 'center', justifyContent: 'center' }}><Text type="secondary">V{version.version_number}</Text></div>}
          {version.is_selected && <Tag color="green" style={{ position: 'absolute', top: 4, right: 4, fontSize: 10 }}>当前结果</Tag>}
        </div>
        <Space style={{ marginTop: 6, width: '100%', justifyContent: 'space-between' }}>
          <Text strong style={{ fontSize: 12 }} ellipsis={{ tooltip: versionDisplayName(version) }}>{versionDisplayName(version)}</Text>
          <Text type="secondary" style={{ fontSize: 10 }}>V{version.version_number} · seed:{version.seed ?? '-'} · {PROVIDER_LABELS[version.provider] || version.provider}</Text>
        </Space>
        {version.quality_report?.warnings?.length ? <Tag color="orange" style={{ marginTop: 4 }}>质检：{version.quality_report.warnings[0]}</Tag> : <Tag color="green" style={{ marginTop: 4 }}>质检通过</Tag>}
        <Space style={{ marginTop: 6 }} wrap>
          {version.result_url && <Button size="small" icon={<DownloadOutlined />} onClick={() => downloadAiVideo(version.result_url!, versionDownloadName(version))}>下载</Button>}
          <Button size="small" icon={<EditOutlined />} onClick={() => openRenameVersion(version)}>重命名</Button>
          <Button size="small" type={version.is_selected ? 'default' : 'primary'} icon={<CheckOutlined />} onClick={() => handleSelectVersion(version)}>设为当前</Button>
          <Button size="small" danger icon={<DeleteOutlined />} onClick={() => handleDeleteVersion(version)}>删除</Button>
        </Space>
      </Card>)}
    </div>
  </Drawer>
}
