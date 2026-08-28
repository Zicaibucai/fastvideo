import { describe, expect, it, vi, beforeEach } from 'vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import type { ReactNode } from 'react'
import MembersTab from './MembersTab'
import { ProjectAccessProvider } from '../../hooks/useProjectPermissions'

const collabMocks = vi.hoisted(() => ({
  members: vi.fn(),
  invitations: vi.fn(),
  invite: vi.fn(),
  roles: vi.fn(),
  updateMemberRole: vi.fn(),
  removeMember: vi.fn(),
  transferOwnership: vi.fn(),
  resendInvitation: vi.fn(),
  revokeInvitation: vi.fn(),
}))

vi.mock('../../api', () => ({
  collabApi: collabMocks,
  projectApi: { detail: vi.fn() },
}))

import { projectApi } from '../../api'

const OWNER_MEMBER = {
  id: 'm1',
  project_id: 'p1',
  user_id: 'u-owner',
  role: 'owner',
  status: 'active',
  joined_at: '2026-08-20T10:00:00Z',
  username: 'owner1',
  email: 'owner@fastvideo.cn',
  created_at: '2026-08-20T10:00:00Z',
  updated_at: '2026-08-20T10:00:00Z',
}

const EDITOR_MEMBER = {
  ...OWNER_MEMBER,
  id: 'm2',
  user_id: 'u-editor',
  role: 'media_editor',
  username: 'editor1',
  email: 'editor@fastvideo.cn',
}

function renderTab(permissions: string[], role = 'owner') {
  ;(projectApi.detail as ReturnType<typeof vi.fn>).mockResolvedValue({
    data: { id: 'p1', my_role: role, my_permissions: permissions, review_policy: 'recommended' },
  })
  const wrapper = ({ children }: { children: ReactNode }) => (
    <ProjectAccessProvider projectId="p1">{children}</ProjectAccessProvider>
  )
  return render(<MembersTab projectId="p1" />, { wrapper })
}

describe('MembersTab 成员邀请与角色管理', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    collabMocks.members.mockResolvedValue({ data: [OWNER_MEMBER, EDITOR_MEMBER] })
    collabMocks.invitations.mockResolvedValue({ data: [] })
    collabMocks.roles.mockResolvedValue({ data: [] })
    collabMocks.invite.mockResolvedValue({
      data: {
        id: 'inv1',
        project_id: 'p1',
        email: 'new@fastvideo.cn',
        role: 'reviewer',
        status: 'pending',
        expires_at: '2026-09-03T10:00:00Z',
        invite_token: 'tok-123',
        invite_url: '/invite/accept?token=tok-123',
        created_at: '2026-08-27T10:00:00Z',
        updated_at: '2026-08-27T10:00:00Z',
      },
    })
  })

  it('无 member.manage 权限时隐藏邀请按钮并显示提示', async () => {
    renderTab(['member.view'], 'viewer')
    await waitFor(() => expect(screen.getByText('editor1')).toBeInTheDocument())
    expect(screen.queryByText('邀请成员')).not.toBeInTheDocument()
    expect(screen.getByText(/只有项目所有者可以管理成员/)).toBeInTheDocument()
  })

  it('唯一 owner 显示保护提示，不能移除', async () => {
    renderTab(['member.manage', 'ownership.transfer', 'member.view'])
    await waitFor(() => expect(screen.getByText('owner1')).toBeInTheDocument())
    expect(screen.getByText(/唯一所有者/)).toBeInTheDocument()
    // owner 行没有移除按钮（editor 行才有）
    expect(screen.getAllByText('移除')).toHaveLength(1)
  })

  it('邀请流程：提交邮箱与角色后展示一次性邀请链接', async () => {
    renderTab(['member.manage', 'ownership.transfer', 'member.view'])
    await waitFor(() => expect(screen.getByText('邀请成员')).toBeInTheDocument())
    fireEvent.click(screen.getByText('邀请成员'))
    fireEvent.change(await screen.findByPlaceholderText('member@example.com'), {
      target: { value: 'new@fastvideo.cn' },
    })
    // 选择审核人角色
    const selects = screen.getAllByRole('combobox')
    fireEvent.mouseDown(selects[selects.length - 1])
    fireEvent.click(await screen.findByText('审核人'))
    fireEvent.click(screen.getByText('发送邀请'))
    await waitFor(() =>
      expect(collabMocks.invite).toHaveBeenCalledWith('p1', 'new@fastvideo.cn', 'reviewer'),
    )
    // 邀请链接（含原始令牌）只显示这一次
    await waitFor(() => expect(screen.getByText(/邀请链接仅显示这一次/)).toBeInTheDocument())
    expect(screen.getAllByText(/tok-123/).length).toBeGreaterThan(0)
  })

  it('修改成员角色调用接口', async () => {
    collabMocks.updateMemberRole.mockResolvedValue({ data: EDITOR_MEMBER })
    renderTab(['member.manage', 'member.view'])
    await waitFor(() => expect(screen.getByText('editor1')).toBeInTheDocument())
    const comboboxes = screen.getAllByRole('combobox')
    fireEvent.mouseDown(comboboxes[0])
    fireEvent.click(await screen.findByText('技术编辑'))
    await waitFor(() =>
      expect(collabMocks.updateMemberRole).toHaveBeenCalledWith('p1', 'm2', 'technical_editor'),
    )
  })
})
