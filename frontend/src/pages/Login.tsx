import { useState } from 'react'
import { Card, Form, Input, Button, Tabs, App, Typography, Alert } from 'antd'
import { LockOutlined, MailOutlined, UserOutlined, BuildOutlined } from '@ant-design/icons'
import { useNavigate } from 'react-router-dom'
import { useAuth } from '../stores/auth'

const { Title, Text } = Typography

export default function Login() {
  const { login, register } = useAuth()
  const navigate = useNavigate()
  const { message } = App.useApp()
  const [loading, setLoading] = useState(false)

  const onLogin = async (values: { email: string; password: string }) => {
    setLoading(true)
    try {
      await login(values.email, values.password)
      message.success('登录成功')
      navigate('/')
    } catch {
      // 错误已由拦截器提示
    } finally {
      setLoading(false)
    }
  }

  const onRegister = async (values: {
    email: string
    username: string
    password: string
    company?: string
  }) => {
    setLoading(true)
    try {
      await register(values)
      message.success('注册成功，请登录')
    } catch {
      // 错误已由拦截器提示
    } finally {
      setLoading(false)
    }
  }

  return (
    <div
      style={{
        minHeight: '100vh',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        background: 'linear-gradient(135deg, #0f2b46 0%, #1d4ed8 100%)',
      }}
    >
      <Card style={{ width: 420, borderRadius: 12, boxShadow: '0 12px 40px rgba(0,0,0,0.2)' }}>
        <div style={{ textAlign: 'center', marginBottom: 16 }}>
          <BuildOutlined style={{ fontSize: 40, color: '#1d4ed8' }} />
          <Title level={3} style={{ marginTop: 8 }}>
            建筑工程AI投标视频平台
          </Title>
          <Text type="secondary">招标文件 → 解说词 → AI画面 → 配音 → 投标视频</Text>
        </div>

        <Alert
          type="info"
          showIcon
          style={{ marginBottom: 16 }}
          message="演示账号"
          description="admin@fastvideo.cn / admin123456（首次启动自动创建）"
        />

        <Tabs
          defaultActiveKey="login"
          items={[
            {
              key: 'login',
              label: '登录',
              children: (
                <Form onFinish={onLogin} layout="vertical">
                  <Form.Item name="email" rules={[{ required: true, message: '请输入邮箱' }]}>
                    <Input prefix={<MailOutlined />} placeholder="邮箱" />
                  </Form.Item>
                  <Form.Item name="password" rules={[{ required: true, message: '请输入密码' }]}>
                    <Input.Password prefix={<LockOutlined />} placeholder="密码" />
                  </Form.Item>
                  <Button type="primary" htmlType="submit" block loading={loading}>
                    登录
                  </Button>
                </Form>
              ),
            },
            {
              key: 'register',
              label: '注册',
              children: (
                <Form onFinish={onRegister} layout="vertical">
                  <Form.Item name="email" rules={[{ required: true, message: '请输入邮箱' }]}>
                    <Input prefix={<MailOutlined />} placeholder="邮箱" />
                  </Form.Item>
                  <Form.Item name="username" rules={[{ required: true, message: '请输入用户名' }]}>
                    <Input prefix={<UserOutlined />} placeholder="用户名" />
                  </Form.Item>
                  <Form.Item name="company">
                    <Input prefix={<BuildOutlined />} placeholder="单位名称（可选）" />
                  </Form.Item>
                  <Form.Item name="password" rules={[{ required: true, min: 6, message: '密码至少 6 位' }]}>
                    <Input.Password prefix={<LockOutlined />} placeholder="密码" />
                  </Form.Item>
                  <Button type="primary" htmlType="submit" block loading={loading}>
                    注册
                  </Button>
                </Form>
              ),
            },
          ]}
        />
      </Card>
    </div>
  )
}
