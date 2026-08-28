import axios from 'axios'
import { Modal, message } from 'antd'

type ValidationErrorItem = {
  loc?: Array<string | number>
  msg?: string
}

const api = axios.create({
  baseURL: '/api/v1',
  timeout: 300000, // 长任务可能耗时较长
  withCredentials: true,
})

// 响应拦截器：统一错误提示。浏览器认证使用 HttpOnly Cookie，避免 JWT
// 出现在 localStorage、媒体 URL、历史记录和代理日志中。
api.interceptors.response.use(
  (response) => {
    return response
  },
  (error) => {
    const status = error.response?.status
    const data = error.response?.data
    const validationErrors = data?.detail?.errors
    const validationMessage = Array.isArray(validationErrors)
      ? validationErrors
        .map((item: ValidationErrorItem) => `${item.loc?.join('.') || '参数'}: ${item.msg || '无效值'}`)
        .join('；')
      : ''
    const msg = validationMessage || data?.message || error.message || '请求失败'
    if (status === 401) {
      if (!window.location.pathname.startsWith('/login')) {
        window.location.href = '/login'
      }
    } else if (status === 409 && data?.detail?.conflict === 'revision') {
      // 并发编辑冲突：不静默覆盖，允许用户重新加载服务器版本；
      // 未提交的编辑内容保留在页面上供复制或比较。
      Modal.confirm({
        title: '内容刚被其他成员修改',
        content: `${msg}（服务器版本 r${data.detail.server_revision}，你基于 r${data.detail.base_revision}）。选择「保留我的编辑」可留在当前页面复制你的修改内容。`,
        okText: '加载最新版本',
        cancelText: '保留我的编辑',
        onOk: () => window.location.reload(),
      })
    } else {
      message.error(msg)
    }
    return Promise.reject(error)
  },
)

export default api

/** 文件 URL 直接使用当前 HttpOnly Cookie 鉴权，不再拼接 JWT 查询参数。 */
export function withAuthToken(url: string): string {
  return url
}
