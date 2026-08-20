import { useEffect, useMemo, useState } from 'react'
import { Layout, Menu, Button, Dropdown, Avatar, Tag } from 'antd'
import type { MenuProps } from 'antd'
import {
  HomeOutlined,
  FolderOpenOutlined,
  VideoCameraOutlined,
  FileTextOutlined,
  SoundOutlined,
  AudioOutlined,
  ExportOutlined,
  UserOutlined,
  LogoutOutlined,
  ExperimentOutlined,
  BookOutlined,
  DatabaseOutlined,
  BgColorsOutlined,
  VideoCameraAddOutlined,
  ProjectOutlined,
} from '@ant-design/icons'
import { Outlet, useNavigate, useLocation } from 'react-router-dom'
import { useAuth } from '../stores/auth'
import { systemApi, projectApi } from '../api'

const { Sider, Header, Content } = Layout

// 会话内记住最近打开的项目，避免离开项目页后左侧项目菜单整个消失
const CURRENT_PROJECT_KEY = 'fastvideo_current_project_id'
const PROJECT_WORKSPACE_KEY = '__project_workspace__'

/** 某个项目下的全部工作区页面（渲染为二级菜单项） */
function projectWorkspaceItems(projectId: string): NonNullable<MenuProps['items']> {
  return [
    { key: `/project/${projectId}`, icon: <FileTextOutlined />, label: '招标资料' },
    { key: `/project/${projectId}/reader`, icon: <BookOutlined />, label: '文档阅读器' },
    { key: `/project/${projectId}/facts`, icon: <DatabaseOutlined />, label: '工程参数台账' },
    { key: `/project/${projectId}/storyboard`, icon: <VideoCameraOutlined />, label: '解说词与分镜' },
    { key: `/project/${projectId}/render`, icon: <BgColorsOutlined />, label: '画面制作' },
    { key: `/project/${projectId}/ai-video`, icon: <VideoCameraAddOutlined />, label: 'AI 视频生成' },
    { key: `/project/${projectId}/voice`, icon: <AudioOutlined />, label: '配音制作' },
    { key: `/project/${projectId}/assets`, icon: <SoundOutlined />, label: '素材库' },
    { key: `/project/${projectId}/video`, icon: <ExportOutlined />, label: '视频工程与导出' },
  ]
}

/** 根据当前路径找出应高亮的菜单 key：取匹配到的最长前缀，根路径仅精确匹配 */
function findSelectedKey(pathname: string, items: MenuProps['items']): string {
  let best = '/'
  let bestLen = -1
  const walk = (list: MenuProps['items']) => {
    for (const item of list ?? []) {
      if (!item) continue
      if ('children' in item && item.children) {
        walk(item.children as MenuProps['items'])
      } else if ('key' in item && typeof item.key === 'string') {
        const key = item.key
        if (key === '/') {
          if (pathname === '/') {
            best = '/'
            bestLen = 0
          }
        } else if (pathname === key || pathname.startsWith(`${key}/`)) {
          if (key.length > bestLen) {
            best = key
            bestLen = key.length
          }
        }
      }
    }
  }
  walk(items)
  return best
}

export default function AppLayout() {
  const navigate = useNavigate()
  const location = useLocation()
  const { user, logout } = useAuth()
  const [mockMode, setMockMode] = useState(false)
  const [collapsed, setCollapsed] = useState(false)
  const [projectName, setProjectName] = useState<string | null>(null)

  // 当前项目 ID：优先取 URL，其次取本会话最近打开过的项目
  const pathSegs = location.pathname.split('/').filter(Boolean)
  const urlProjectId = pathSegs[0] === 'project' && pathSegs[1] ? pathSegs[1] : null
  const [currentProjectId, setCurrentProjectId] = useState<string | null>(() =>
    urlProjectId ?? sessionStorage.getItem(CURRENT_PROJECT_KEY),
  )
  const [openKeys, setOpenKeys] = useState<string[]>(() =>
    currentProjectId ? [PROJECT_WORKSPACE_KEY] : [],
  )

  // 进入项目页时记住项目，保证切到「项目总览 / 投标项目」后菜单仍然稳定
  useEffect(() => {
    if (urlProjectId) {
      sessionStorage.setItem(CURRENT_PROJECT_KEY, urlProjectId)
      setCurrentProjectId(urlProjectId)
    }
  }, [urlProjectId])

  // 有当前项目时始终保持工作区菜单展开
  useEffect(() => {
    setOpenKeys((prev) =>
      currentProjectId
        ? prev.includes(PROJECT_WORKSPACE_KEY)
          ? prev
          : [...prev, PROJECT_WORKSPACE_KEY]
        : [],
    )
  }, [currentProjectId])

  // 拉取当前项目名称作为分组标题（仅当 URL 确实指向项目时请求，避免为过期记忆报错）
  useEffect(() => {
    if (!urlProjectId) return
    let cancelled = false
    projectApi
      .detail(urlProjectId)
      .then((res) => {
        if (!cancelled) setProjectName(res.data.name)
      })
      .catch(() => {
        if (!cancelled) setProjectName(null)
      })
    return () => {
      cancelled = true
    }
  }, [urlProjectId])

  useEffect(() => {
    systemApi
      .status()
      .then((res) => setMockMode(res.data.ai.mock_mode))
      .catch(() => {})
  }, [])

  const menuItems = useMemo<MenuProps['items']>(() => {
    const items: NonNullable<MenuProps['items']> = [
      { key: '/', icon: <HomeOutlined />, label: '项目总览' },
      { key: '/projects', icon: <FolderOpenOutlined />, label: '投标项目' },
    ]
    if (currentProjectId) {
      items.push(
        { type: 'divider' },
        {
          key: PROJECT_WORKSPACE_KEY,
          icon: <ProjectOutlined />,
          label: projectName || '当前项目',
          className: 'workspace-submenu-title',
          children: projectWorkspaceItems(currentProjectId),
        },
      )
    }
    return items
  }, [currentProjectId, projectName])

  const selectedKey = useMemo(
    () => findSelectedKey(location.pathname, menuItems),
    [location.pathname, menuItems],
  )

  return (
    <Layout style={{ minHeight: '100vh' }}>
      <Sider
        className="app-sider"
        collapsible
        collapsed={collapsed}
        onCollapse={setCollapsed}
        theme="dark"
        width={232}
      >
        <div className="app-logo">🏗️ {collapsed ? '' : 'AI投标视频平台'}</div>
        <Menu
          theme="dark"
          mode="inline"
          selectedKeys={[selectedKey]}
          openKeys={openKeys}
          onOpenChange={setOpenKeys}
          items={menuItems}
          onClick={({ key }) => navigate(key)}
        />
      </Sider>
      <Layout>
        <Header
          style={{
            background: '#fff',
            padding: '0 24px',
            display: 'flex',
            justifyContent: 'space-between',
            alignItems: 'center',
            boxShadow: '0 1px 4px rgba(0,0,0,0.06)',
          }}
        >
          <div>
            {mockMode && (
              <Tag color="orange" icon={<ExperimentOutlined />}>
                Mock 演示模式（核心 AI 服务未配置）
              </Tag>
            )}
          </div>
          <Dropdown
            menu={{
              items: [{ key: 'logout', icon: <LogoutOutlined />, label: '退出登录' }],
              onClick: ({ key }) => {
                if (key === 'logout') {
                  logout()
                  navigate('/login')
                }
              },
            }}
          >
            <Button type="text" style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <Avatar size="small" icon={<UserOutlined />} />
              {user?.username || '未登录'}
            </Button>
          </Dropdown>
        </Header>
        <Content style={{ margin: 16 }}>
          <Outlet />
        </Content>
      </Layout>
    </Layout>
  )
}
