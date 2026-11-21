import axios from 'axios'
import { ElMessage } from 'element-plus'
import router from './router'
import { i18n } from './i18n'

const api = axios.create({ baseURL: '/api', timeout: 20000 })

api.interceptors.request.use((cfg) => {
  const token = localStorage.getItem('token')
  if (token) cfg.headers.Authorization = `Bearer ${token}`
  return cfg
})

api.interceptors.response.use(
  (r) => r,
  (err) => {
    const status = err.response?.status
    if (status === 401 && router.currentRoute.value.name !== 'login') {
      localStorage.removeItem('token')
      router.push({ name: 'login' })
    } else if (!err.config?.silent) {
      const detail = err.response?.data?.detail
      ElMessage.error(typeof detail === 'string' ? detail : i18n.global.t('common.requestFailed'))
    }
    return Promise.reject(err)
  },
)

export default api
