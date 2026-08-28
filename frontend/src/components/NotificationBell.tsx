import { useCallback, useEffect, useRef, useState } from 'react'
import { Badge, Button, Dropdown, List, Space, Typography } from 'antd'
import { BellOutlined } from '@ant-design/icons'
import { useNavigate } from 'react-router-dom'
import { notificationApi } from '../api'
import type { AppNotification } from '../api/types'

const { Text } = Typography

/** 全局通知铃铛：未读数轮询 + 下拉列表 + 跳转 */
export default function NotificationBell() {
  const navigate = useNavigate()
  const [count, setCount] = useState(0)
  const [items, setItems] = useState<AppNotification[]>([])
  const [open, setOpen] = useState(false)
  const timer = useRef<ReturnType<typeof setInterval> | null>(null)

  const refreshCount = useCallback(async () => {
    if (document.visibilityState !== 'visible') return
    try {
      const resp = await notificationApi.unreadCount()
      setCount(resp.data.count)
    } catch {
      /* 忽略轮询错误 */
    }
  }, [])

  useEffect(() => {
    void refreshCount()
    timer.current = setInterval(() => void refreshCount(), 30_000)
    return () => {
      if (timer.current) clearInterval(timer.current)
    }
  }, [refreshCount])

  const loadItems = async () => {
    const resp = await notificationApi.list({ limit: 20 })
    setItems(resp.data)
  }

  const openItem = async (item: AppNotification) => {
    if (!item.is_read) {
      await notificationApi.markRead(item.id)
      setCount((c) => Math.max(0, c - 1))
    }
    setOpen(false)
    if (item.link) navigate(item.link)
  }

  return (
    <Dropdown
      open={open}
      onOpenChange={(v) => {
        setOpen(v)
        if (v) void loadItems()
      }}
      trigger={['click']}
      placement="bottomRight"
      dropdownRender={() => (
        <div
          style={{
            width: 360,
            maxHeight: 420,
            overflow: 'auto',
            background: '#fff',
            borderRadius: 8,
            boxShadow: '0 6px 16px rgba(0,0,0,0.12)',
          }}
        >
          <Space style={{ padding: '8px 12px', justifyContent: 'space-between', width: '100%' }}>
            <Text strong>通知</Text>
            <Button
              type="link"
              size="small"
              onClick={() => {
                void notificationApi.markAllRead().then(() => {
                  setCount(0)
                  void loadItems()
                })
              }}
            >
              全部已读
            </Button>
          </Space>
          <List
            size="small"
            dataSource={items}
            locale={{ emptyText: '暂无通知' }}
            renderItem={(item) => (
              <List.Item
                style={{
                  padding: '8px 12px',
                  cursor: 'pointer',
                  background: item.is_read ? undefined : '#f0f5ff',
                }}
                onClick={() => void openItem(item)}
              >
                <div>
                  <div style={{ fontWeight: item.is_read ? 400 : 600 }}>{item.title}</div>
                  {item.body && (
                    <Text type="secondary" style={{ fontSize: 12 }} ellipsis>
                      {item.body}
                    </Text>
                  )}
                  <div>
                    <Text type="secondary" style={{ fontSize: 11 }}>
                      {new Date(item.created_at).toLocaleString('zh-CN')}
                    </Text>
                  </div>
                </div>
              </List.Item>
            )}
          />
        </div>
      )}
    >
      <Badge count={count} size="small">
        <Button type="text" icon={<BellOutlined style={{ fontSize: 18 }} />} aria-label="通知" />
      </Badge>
    </Dropdown>
  )
}
