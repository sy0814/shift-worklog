import axios from 'axios'
import { ElMessage } from 'element-plus'
import router from './router'
import { i18n } from './i18n'
import { net, noteResponse } from './net'
import { translateError } from './apiErrors'
import { getDept } from './dept'

const api = axios.create({ baseURL: '/api', timeout: 20000 })

api.interceptors.request.use((cfg) => {
  const token = localStorage.getItem('token')
  if (token) cfg.headers.Authorization = `Bearer ${token}`
  const dept = getDept()
  if (dept && !cfg.headers['X-Department']) cfg.headers['X-Department'] = String(dept)
  return cfg
})

api.interceptors.response.use(
  (r) => {
    noteResponse(r)
    return r
  },
  (err) => {
    if (!err.response) {
      // 没有响应 = 网络不通；离线时不弹错误，由页面顶部的离线提示说明
      net.online = false
      if (!err.config?.silent && navigator.onLine) ElMessage.error(i18n.global.t('common.requestFailed'))
      return Promise.reject(err)
    }
    const status = err.response?.status
    if (status === 401 && router.currentRoute.value.name !== 'login') {
      localStorage.removeItem('token')
      router.push({ name: 'login' })
    } else if (status === 403 && err.response?.data?.detail === 'password change required') {
      if (router.currentRoute.value.name !== 'change-password') router.push({ name: 'change-password' })
    } else if (!err.config?.silent) {
      const detail = err.response?.data?.detail
      ElMessage.error(typeof detail === 'string'
        ? translateError(detail, i18n.global.locale.value, i18n.global.t) : i18n.global.t('common.requestFailed'))
    }
    return Promise.reject(err)
  },
)

export default api

/** 带登录令牌下载文件（Excel、CSV 等） */
export async function download(url, params, fallbackName) {
  const res = await api.get(url, { params, responseType: 'blob', timeout: 120000 })
  const cd = res.headers['content-disposition'] || ''
  const m = /filename\*=UTF-8''([^;]+)|filename="?([^";]+)"?/.exec(cd)
  const name = m ? decodeURIComponent(m[1] || m[2]) : fallbackName
  const a = document.createElement('a')
  a.href = URL.createObjectURL(res.data)
  a.download = name
  document.body.appendChild(a)
  a.click()
  a.remove()
  setTimeout(() => URL.revokeObjectURL(a.href), 1000)
}
