import { useEffect, useMemo, useState } from 'react'
import { Layout, Menu, Dropdown } from 'antd'
import type { MenuProps } from 'antd'
import {
  HomeOutlined,
  TeamOutlined,
  FolderOpenOutlined,
  VideoCameraOutlined,
  FileTextOutlined,
  SoundOutlined,
  AudioOutlined,
  ExportOutlined,
  BookOutlined,
  DatabaseOutlined,
  BgColorsOutlined,
  VideoCameraAddOutlined,
  MergeCellsOutlined,
  ArrowLeftOutlined,
  DownOutlined,
  SettingOutlined,
  ProjectOutlined,
} from '@ant-design/icons'
import { Outlet, useNavigate, useLocation } from 'react-router-dom'
import { projectApi } from '../api'
import type { Project } from '../api/types'
import { rememberProjectOpened } from '../recentProjects'
import ProjectNotificationCenter, { ProjectNotificationProvider } from './ProjectNotificationCenter'
import { ProjectAccessProvider } from '../hooks/useProjectPermissions'

const { Sider, Content } = Layout

/** 某个项目下的全部工作区页面（渲染为二级菜单项） */
function projectWorkspaceItems(projectId: string): NonNullable<MenuProps['items']> {
  return [
    { key: `/project/${projectId}`, icon: <FileTextOutlined />, label: '招标资料' },
    { key: `/project/${projectId}/reader`, icon: <BookOutlined />, label: '文档阅读器' },
    { key: `/project/${projectId}/facts`, icon: <DatabaseOutlined />, label: '工程信息核对' },
    { key: `/project/${projectId}/storyboard`, icon: <VideoCameraOutlined />, label: '解说词与分镜' },
    { key: `/project/${projectId}/render`, icon: <BgColorsOutlined />, label: '画面制作' },
    { key: `/project/${projectId}/ai-video`, icon: <VideoCameraAddOutlined />, label: 'AI 视频生成' },
    { key: `/project/${projectId}/voice`, icon: <AudioOutlined />, label: '配音制作' },
    { key: `/project/${projectId}/assets`, icon: <SoundOutlined />, label: '素材库' },
    { key: `/project/${projectId}/video`, icon: <ExportOutlined />, label: '合成分镜' },
    { key: `/project/${projectId}/video-concat`, icon: <MergeCellsOutlined />, label: '分镜拼接' },
    { key: `/project/${projectId}/collaboration`, icon: <TeamOutlined />, label: '协作与审核' },
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
  const [collapsed, setCollapsed] = useState(() =>
    typeof window !== 'undefined' && window.innerWidth < 1100,
  )
  const [projectName, setProjectName] = useState<string | null>(null)
  const [projects, setProjects] = useState<Project[]>([])

  const pathSegs = location.pathname.split('/').filter(Boolean)
  const urlProjectId = pathSegs[0] === 'project' && pathSegs[1] ? pathSegs[1] : null

  useEffect(() => {
    if (!urlProjectId) return
    rememberProjectOpened(urlProjectId)
    let cancelled = false
    Promise.all([
      projectApi.detail(urlProjectId),
      projectApi.list({ page_size: 100 }),
    ])
      .then(([detail, list]) => {
        if (!cancelled) {
          setProjectName(detail.data.name)
          setProjects(list.data.items)
        }
      })
      .catch(() => {
        if (!cancelled) {
          setProjectName(null)
          setProjects([])
        }
      })
    return () => {
      cancelled = true
    }
  }, [urlProjectId])

  useEffect(() => {
    const media = window.matchMedia('(max-width: 1099px)')
    const syncCollapsed = () => setCollapsed(media.matches)
    syncCollapsed()
    media.addEventListener('change', syncCollapsed)
    return () => media.removeEventListener('change', syncCollapsed)
  }, [])

  const menuItems = useMemo<MenuProps['items']>(() => {
    if (!urlProjectId) {
      return [
        { key: '/', icon: <HomeOutlined />, label: '项目总览' },
        { key: '/projects', icon: <FolderOpenOutlined />, label: '投标项目' },
        { key: '/account-settings', icon: <SettingOutlined />, label: '账号与 AI 设置' },
      ]
    }
    const workspaceItems = projectWorkspaceItems(urlProjectId)
    return [
      { key: '/projects', icon: <ArrowLeftOutlined />, label: '返回投标项目' },
      { type: 'divider' },
      ...(collapsed
        ? workspaceItems
        : [{ type: 'group' as const, label: '项目工作区', children: workspaceItems }]),
    ]
  }, [collapsed, urlProjectId])

  const selectedKey = useMemo(
    () => findSelectedKey(location.pathname, menuItems),
    [location.pathname, menuItems],
  )

  const projectSwitcherItems = projects.map((project) => ({
    key: project.id,
    label: project.name,
  }))

  return (
    <Layout className="app-root-layout" style={{ minHeight: '100dvh' }}>
      <Sider
        className="app-sider"
        collapsible
        collapsed={collapsed}
        onCollapse={setCollapsed}
        theme="light"
        width={216}
        collapsedWidth={64}
      >
        <div className={`app-logo${collapsed ? ' is-collapsed' : ''}`} aria-label="微影">
          {collapsed ? (
            <ProjectOutlined className="app-brand-mark" aria-hidden="true" />
          ) : (
            <>
              <span className="app-brand-name">微影</span>
              <span className="app-brand-credit">由中建八局制作</span>
            </>
          )}
        </div>
        {urlProjectId && !collapsed && (
          <Dropdown
            trigger={['click']}
            menu={{
              items: projectSwitcherItems,
              onClick: ({ key }) => navigate(`/project/${key}`),
            }}
          >
            <button type="button" className="app-project-switcher">
              <span className="app-project-switcher-label">当前项目</span>
              <span className="app-project-switcher-name">{projectName || '加载项目中'}</span>
              <DownOutlined className="app-project-switcher-icon" />
            </button>
          </Dropdown>
        )}
        <Menu
          theme="light"
          mode="inline"
          selectedKeys={[selectedKey]}
          items={menuItems}
          onClick={({ key }) => navigate(key)}
        />
      </Sider>
      <Layout className="app-main-layout">
        <ProjectNotificationProvider key={urlProjectId || 'global'}>
          <div className="app-notice-fab">
            <ProjectNotificationCenter projectId={urlProjectId} />
          </div>
          <Content className="app-content" style={{ padding: '28px 32px 40px' }}>
            <div className="app-content-inner">
              {urlProjectId ? (
                <ProjectAccessProvider key={urlProjectId} projectId={urlProjectId}>
                  <Outlet />
                </ProjectAccessProvider>
              ) : (
                <Outlet />
              )}
            </div>
          </Content>
        </ProjectNotificationProvider>
      </Layout>
    </Layout>
  )
}
