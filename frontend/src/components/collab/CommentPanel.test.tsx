import { describe, expect, it, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import { fireEvent } from '@testing-library/react'
import type { ReactNode } from 'react'
import CommentPanel from './CommentPanel'
import { ProjectAccessProvider } from '../../hooks/useProjectPermissions'

const collabMocks = vi.hoisted(() => ({
  comments: vi.fn(),
  createComment: vi.fn(),
  resolveComment: vi.fn(),
  reopenComment: vi.fn(),
  deleteComment: vi.fn(),
  updateComment: vi.fn(),
}))

vi.mock('../../api', () => ({
  collabApi: collabMocks,
  projectApi: {
    detail: vi.fn(),
  },
}))

import { projectApi } from '../../api'

const COMMENT = {
  id: 'c1',
  project_id: 'p1',
  target_type: 'storyboard',
  target_id: undefined,
  target_label: '解说词与分镜（整份文稿）',
  author_id: 'u1',
  author_name: '张工',
  parent_id: undefined,
  body: '第二分镜工期数据需要复核',
  is_blocking: true,
  status: 'open',
  created_at: '2026-08-27T10:00:00Z',
  updated_at: '2026-08-27T10:00:00Z',
}

function renderPanel(permissions: string[], role = 'media_editor') {
  ;(projectApi.detail as ReturnType<typeof vi.fn>).mockResolvedValue({
    data: { id: 'p1', my_role: role, my_permissions: permissions, review_policy: 'recommended' },
  })
  const wrapper = ({ children }: { children: ReactNode }) => (
    <ProjectAccessProvider projectId="p1">{children}</ProjectAccessProvider>
  )
  return render(
    <CommentPanel projectId="p1" targetType="storyboard" />,
    { wrapper },
  )
}

describe('CommentPanel 评论侧栏', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    collabMocks.comments.mockResolvedValue({ data: [COMMENT] })
    collabMocks.createComment.mockResolvedValue({ data: COMMENT })
    collabMocks.resolveComment.mockResolvedValue({ data: { ...COMMENT, status: 'resolved' } })
  })

  it('渲染评论列表与作者、内容、阻断标记', async () => {
    renderPanel(['comment.view', 'comment.create', 'comment.resolve'])
    await waitFor(() => expect(screen.getByText('第二分镜工期数据需要复核')).toBeInTheDocument())
    expect(screen.getByText('张工')).toBeInTheDocument()
    expect(screen.getByText('阻断')).toBeInTheDocument()
  })

  it('viewer 角色不可见发表评论入口', async () => {
    renderPanel(['comment.view'], 'viewer')
    await waitFor(() => expect(screen.getByText('第二分镜工期数据需要复核')).toBeInTheDocument())
    expect(screen.queryByText('发表评论')).not.toBeInTheDocument()
    expect(screen.getByText(/只读/)).toBeInTheDocument()
  })

  it('有 comment.create 权限时可发表评论', async () => {
    renderPanel(['comment.view', 'comment.create'])
    await waitFor(() => expect(screen.getByText('第二分镜工期数据需要复核')).toBeInTheDocument())
    fireEvent.change(screen.getByPlaceholderText(/写下评论/), { target: { value: '收到，马上修改' } })
    fireEvent.click(screen.getByText('发表评论'))
    await waitFor(() =>
      expect(collabMocks.createComment).toHaveBeenCalledWith('p1', expect.objectContaining({
        target_type: 'storyboard',
        body: '收到，马上修改',
      })),
    )
  })

  it('有 comment.resolve 权限时可解决评论', async () => {
    renderPanel(['comment.view', 'comment.resolve'])
    await waitFor(() => expect(screen.getByText('第二分镜工期数据需要复核')).toBeInTheDocument())
    fireEvent.click(screen.getByText('解决'))
    await waitFor(() => expect(collabMocks.resolveComment).toHaveBeenCalledWith('p1', 'c1'))
  })

  it('无 comment.resolve 权限时隐藏解决按钮', async () => {
    renderPanel(['comment.view', 'comment.create'])
    await waitFor(() => expect(screen.getByText('第二分镜工期数据需要复核')).toBeInTheDocument())
    expect(screen.queryByText('解决')).not.toBeInTheDocument()
  })
})
