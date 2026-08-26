import { useState } from 'react'
import type { ReactNode } from 'react'
import { Badge, Button, Empty, Popover, Progress, Typography } from 'antd'
import {
  BellOutlined,
  CheckCircleOutlined,
  CloseCircleOutlined,
  InfoCircleOutlined,
  WarningOutlined,
} from '@ant-design/icons'

const { Text } = Typography

export type NoticeTone = 'info' | 'success' | 'warning' | 'error'

export interface NoticeItem {
  key: string
  tone: NoticeTone
  title: string
  description?: ReactNode
  progress?: number
  action?: ReactNode
}

const toneIcon: Record<NoticeTone, ReactNode> = {
  info: <InfoCircleOutlined />,
  success: <CheckCircleOutlined />,
  warning: <WarningOutlined />,
  error: <CloseCircleOutlined />,
}

export default function FloatingNoticeCenter({ items }: { items: NoticeItem[] }) {
  const [open, setOpen] = useState(false)

  const panel = (
    <section
      className="notice-center-panel"
      aria-label="通知中心"
      onClick={(event) => {
        if ((event.target as HTMLElement).closest('button')) setOpen(false)
      }}
    >
      <header className="notice-center-header">
        <Text strong>通知</Text>
        <Text type="secondary">{items.length > 0 ? `${items.length} 项通知` : '当前无通知'}</Text>
      </header>

      <div className="notice-center-list">
        {items.length === 0 ? (
          <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无通知" />
        ) : (
          items.map((item) => (
            <article key={item.key} className={`notice-center-item notice-center-item-${item.tone}`}>
              <span className="notice-center-item-icon" aria-hidden="true">
                {toneIcon[item.tone]}
              </span>
              <div className="notice-center-item-body">
                <Text strong className="notice-center-item-title">{item.title}</Text>
                {item.description && (
                  <div className="notice-center-item-description">{item.description}</div>
                )}
                {typeof item.progress === 'number' && item.progress > 0 && (
                  <Progress
                    percent={Math.max(0, Math.min(100, item.progress))}
                    size="small"
                    status="active"
                    className="notice-center-progress"
                  />
                )}
                {item.action && <div className="notice-center-item-action">{item.action}</div>}
              </div>
            </article>
          ))
        )}
      </div>
    </section>
  )

  return (
    <div className="notice-center-fab">
      <Popover
        content={panel}
        trigger="click"
        placement="topRight"
        arrow={false}
        open={open}
        onOpenChange={setOpen}
        overlayClassName="notice-center-popover"
      >
          <Badge
            count={items.length}
            size="small"
            overflowCount={99}
            showZero={false}
            className="notice-center-badge"
          >
            <Button
              type="default"
              shape="circle"
              icon={<BellOutlined />}
            className="notice-center-trigger"
            aria-label={`打开通知中心，${items.length} 项通知`}
          />
        </Badge>
      </Popover>
    </div>
  )
}
