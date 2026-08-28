import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react'
import type { ReactNode } from 'react'
import { projectApi } from '../api'
import type { Project, ProjectRole } from '../api/types'

export interface ProjectAccessValue {
  projectId: string
  project: Project | null
  role: ProjectRole | null
  permissions: Set<string>
  reviewPolicy: 'disabled' | 'recommended' | 'required'
  loading: boolean
  has: (permission: string) => boolean
  refresh: () => Promise<void>
}

const ProjectAccessContext = createContext<ProjectAccessValue | null>(null)

/**
 * 项目级权限上下文：从后端项目详情读取当前用户的角色与权限集合。
 * 前端仅用于控制按钮可见性/禁用状态，后端仍逐接口强制校验。
 */
export function ProjectAccessProvider({
  projectId,
  children,
}: {
  projectId: string
  children: ReactNode
}) {
  const [project, setProject] = useState<Project | null>(null)
  const [loading, setLoading] = useState(true)

  const load = useCallback(async () => {
    try {
      const resp = await projectApi.detail(projectId)
      setProject(resp.data)
    } catch {
      setProject(null)
    } finally {
      setLoading(false)
    }
  }, [projectId])

  useEffect(() => {
    setLoading(true)
    void load()
  }, [load])

  const value = useMemo<ProjectAccessValue>(() => {
    const permissions = new Set<string>(project?.my_permissions ?? [])
    return {
      projectId,
      project,
      role: project?.my_role ?? null,
      permissions,
      reviewPolicy: project?.review_policy ?? 'recommended',
      loading,
      has: (permission: string) => permissions.has(permission),
      refresh: load,
    }
  }, [project, projectId, loading, load])

  return <ProjectAccessContext.Provider value={value}>{children}</ProjectAccessContext.Provider>
}

const EMPTY_VALUE: ProjectAccessValue = {
  projectId: '',
  project: null,
  role: null,
  permissions: new Set<string>(),
  reviewPolicy: 'recommended',
  loading: false,
  has: () => false,
  refresh: async () => {},
}

/** 读取当前项目权限；不在项目上下文（或加载失败）时返回空权限集合。 */
export function useProjectPermissions(): ProjectAccessValue {
  return useContext(ProjectAccessContext) ?? EMPTY_VALUE
}

export const ROLE_LABELS: Record<string, string> = {
  owner: '项目所有者',
  bid_manager: '投标负责人',
  technical_editor: '技术编辑',
  media_editor: '视频编辑',
  reviewer: '审核人',
  viewer: '只读成员',
}

export const REVIEW_STATE_LABELS: Record<string, string> = {
  draft: '未提交审核',
  in_review: '审核中',
  changes_requested: '要求修改',
  approved: '已批准',
  approved_but_changed: '批准后已变更',
}

export const REVIEW_STATE_COLORS: Record<string, string> = {
  draft: 'default',
  in_review: 'processing',
  changes_requested: 'warning',
  approved: 'success',
  approved_but_changed: 'error',
}
