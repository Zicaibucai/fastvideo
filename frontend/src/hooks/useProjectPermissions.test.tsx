import { describe, expect, it, vi } from 'vitest'
import { renderHook } from '@testing-library/react'
import type { ReactNode } from 'react'
import { ProjectAccessProvider, useProjectPermissions } from './useProjectPermissions'

const mocks = vi.hoisted(() => ({
  detail: vi.fn(),
  list: vi.fn(),
  create: vi.fn(),
  enter: vi.fn(),
  update: vi.fn(),
  remove: vi.fn(),
}))

vi.mock('../api', () => ({ projectApi: mocks }))

function wrapper(projectId: string) {
  return function Wrapper({ children }: { children: ReactNode }) {
    return <ProjectAccessProvider projectId={projectId}>{children}</ProjectAccessProvider>
  }
}

describe('useProjectPermissions', () => {
  it('不在项目上下文时返回空权限集合', () => {
    const { result } = renderHook(() => useProjectPermissions())
    expect(result.current.role).toBeNull()
    expect(result.current.has('project.edit')).toBe(false)
    expect(result.current.has('project.view')).toBe(false)
  })

  it('owner 拥有全部权限', async () => {
    mocks.detail.mockResolvedValue({
      data: {
        id: 'p1',
        my_role: 'owner',
        my_permissions: ['project.view', 'member.manage', 'export.formal'],
        review_policy: 'required',
      },
    })
    const { result } = renderHook(() => useProjectPermissions(), { wrapper: wrapper('p1') })
    await vi.waitFor(() => expect(result.current.loading).toBe(false))
    expect(result.current.role).toBe('owner')
    expect(result.current.has('member.manage')).toBe(true)
    expect(result.current.has('export.formal')).toBe(true)
    expect(result.current.reviewPolicy).toBe('required')
  })

  it('viewer 只有查看权限，编辑类权限为 false', async () => {
    mocks.detail.mockResolvedValue({
      data: {
        id: 'p1',
        my_role: 'viewer',
        my_permissions: ['project.view', 'fact.view', 'storyboard.view'],
        review_policy: 'recommended',
      },
    })
    const { result } = renderHook(() => useProjectPermissions(), { wrapper: wrapper('p1') })
    await vi.waitFor(() => expect(result.current.loading).toBe(false))
    expect(result.current.role).toBe('viewer')
    expect(result.current.has('fact.view')).toBe(true)
    expect(result.current.has('fact.edit')).toBe(false)
    expect(result.current.has('review.submit')).toBe(false)
    expect(result.current.has('member.manage')).toBe(false)
  })

  it('详情加载失败时降级为空权限', async () => {
    mocks.detail.mockRejectedValue(new Error('404'))
    const { result } = renderHook(() => useProjectPermissions(), { wrapper: wrapper('p-x') })
    await vi.waitFor(() => expect(result.current.loading).toBe(false))
    expect(result.current.role).toBeNull()
    expect(result.current.has('project.view')).toBe(false)
  })
})
