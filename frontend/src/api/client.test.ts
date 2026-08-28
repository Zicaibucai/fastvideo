import { describe, expect, it, vi, beforeEach } from 'vitest'
import { Modal } from 'antd'
import api from './client'

/**
 * 冲突提示测试：409 + detail.conflict=revision 时弹出冲突对话框，
 * 而不是普通的错误 toast，允许用户选择重新加载或保留编辑。
 */
describe('api client 并发冲突处理', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
  })

  it('revision 冲突触发 Modal.confirm 而非 message.error', async () => {
    const confirmSpy = vi.spyOn(Modal, 'confirm').mockImplementation(() => ({ destroy: () => {}, update: () => {} }) as never)
    api.defaults.adapter = async (config) => {
      const error = Object.assign(new Error('Request failed with status code 409'), {
        config,
        isAxiosError: true,
        response: {
          status: 409,
          statusText: 'Conflict',
          headers: {},
          config,
          data: {
            code: 'CONFLICT',
            message: '该内容刚被其他成员修改，请加载最新版本后再保存',
            detail: { conflict: 'revision', server_revision: 3, base_revision: 2 },
          },
        },
        toJSON: () => ({}),
      })
      throw error
    }
    await expect(api.get('/projects/p1')).rejects.toThrow()
    expect(confirmSpy).toHaveBeenCalledWith(
      expect.objectContaining({ title: '内容刚被其他成员修改' }),
    )
  })

  it('普通 409（非 revision 冲突）走普通错误提示', async () => {
    const confirmSpy = vi.spyOn(Modal, 'confirm')
    api.defaults.adapter = async (config) => {
      throw Object.assign(new Error('Request failed with status code 409'), {
        config,
        isAxiosError: true,
        response: {
          status: 409,
          statusText: 'Conflict',
          headers: {},
          config,
          data: { code: 'CONFLICT', message: '最后一个所有者不能退出' },
        },
        toJSON: () => ({}),
      })
    }
    await expect(api.get('/projects/p1')).rejects.toThrow()
    expect(confirmSpy).not.toHaveBeenCalled()
  })
})
