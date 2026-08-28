import { useEffect, useState } from 'react'
import { Alert, Button, Card, Input, Result, Space, Typography, message } from 'antd'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { collabApi } from '../api'

const { Text } = Typography

/** 接受项目邀请：通过邀请链接进入（/invite/accept?token=...）或手动粘贴令牌 */
export default function AcceptInvite() {
  const [searchParams] = useSearchParams()
  const navigate = useNavigate()
  const [token, setToken] = useState(searchParams.get('token') || '')
  const [result, setResult] = useState<'pending' | 'success' | 'error'>('pending')
  const [errorMsg, setErrorMsg] = useState('')
  const [projectId, setProjectId] = useState<string | null>(null)

  const accept = async (value: string) => {
    try {
      const resp = await collabApi.acceptInvitation(value)
      setProjectId(resp.data.project_id)
      setResult('success')
    } catch (err) {
      const detail = (err as { response?: { data?: { message?: string } } }).response?.data?.message
      setErrorMsg(detail || '接受邀请失败')
      setResult('error')
    }
  }

  useEffect(() => {
    const t = searchParams.get('token')
    if (t) {
      void accept(t)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  if (result === 'success') {
    return (
      <Result
        status="success"
        title="已加入项目"
        subTitle="你现在可以访问该项目的协作内容"
        extra={
          <Button type="primary" onClick={() => navigate(projectId ? `/project/${projectId}/collaboration` : '/projects')}>
            进入项目
          </Button>
        }
      />
    )
  }

  if (result === 'error') {
    return (
      <Result
        status="error"
        title="无法接受邀请"
        subTitle={errorMsg}
        extra={
          <Space direction="vertical">
            <Text type="secondary">邀请只能由对应邮箱的账号在 7 天内接受一次。</Text>
            <Button onClick={() => setResult('pending')}>重新输入令牌</Button>
          </Space>
        }
      />
    )
  }

  return (
    <div style={{ maxWidth: 480, margin: '80px auto' }}>
      <Card title="接受项目邀请">
        <Space direction="vertical" style={{ width: '100%' }}>
          <Alert type="info" message="粘贴邀请链接或令牌，加入协作项目。" />
          <Input
            value={token}
            onChange={(e) => setToken(e.target.value)}
            placeholder="粘贴邀请链接或令牌"
          />
          <Button
            type="primary"
            disabled={!token.trim()}
            onClick={() => {
              const raw = token.trim()
              const extracted = raw.includes('token=') ? raw.split('token=')[1].split('&')[0] : raw
              void accept(extracted)
            }}
          >
            接受邀请
          </Button>
        </Space>
      </Card>
    </div>
  )
}
