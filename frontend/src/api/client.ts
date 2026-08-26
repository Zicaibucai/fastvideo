import axios from 'axios'
import { message } from 'antd'

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
      ? validationErrors.map((item: any) => `${item.loc?.join('.') || '参数'}: ${item.msg}`).join('；')
      : ''
    const msg = validationMessage || data?.message || error.message || '请求失败'
    if (status === 401) {
      if (!window.location.pathname.startsWith('/login')) {
        window.location.href = '/login'
      }
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
