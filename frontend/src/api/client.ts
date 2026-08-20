import axios from 'axios'
import { message } from 'antd'

const api = axios.create({
  baseURL: '/api/v1',
  timeout: 300000, // 长任务可能耗时较长
})

// 请求拦截器：附加 Token
api.interceptors.request.use((config) => {
  const token = localStorage.getItem('fastvideo_token')
  if (token) {
    config.headers.Authorization = `Bearer ${token}`
  }
  return config
})

// 响应拦截器：统一错误提示
api.interceptors.response.use(
  (response) => response,
  (error) => {
    const status = error.response?.status
    const data = error.response?.data
    const msg = data?.message || error.message || '请求失败'
    if (status === 401) {
      localStorage.removeItem('fastvideo_token')
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
