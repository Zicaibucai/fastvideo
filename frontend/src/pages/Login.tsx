import { useState } from 'react'
import { Card, Form, Input, Button, Tabs, App, Typography } from 'antd'
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
    <div className="login-shell">
      <Card className="login-card">
        <div style={{ textAlign: 'center', marginBottom: 16 }}>
          <div className="login-brand-lockup">
            <div className="login-brand-name">微影</div>
            <div className="login-brand-credit">由中建八局制作</div>
          </div>
          <Title level={3} style={{ marginTop: 8 }}>
            建设项目影像工作台
          </Title>
          <Text type="secondary">从招标资料到投标成片</Text>
        </div>

        <Text type="secondary" style={{ display: 'block', marginBottom: 16, textAlign: 'center', fontSize: 12 }}>
          演示账号：admin@fastvideo.cn / admin123456
        </Text>

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
