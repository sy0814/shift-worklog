// 网络状态：是否在线、当前页面的数据是不是离线缓存（以及缓存时间）
import { reactive } from 'vue'

export const net = reactive({
  online: navigator.onLine,
  cachedAt: null, // 最近一次显示的是缓存数据时，缓存的时间（ISO 字符串）
})

window.addEventListener('online', () => { net.online = true })
window.addEventListener('offline', () => { net.online = false })

export function noteResponse(res) {
  const c = res.headers?.['x-from-cache']
  if (c) {
    net.cachedAt = c === '1' ? net.cachedAt || new Date().toISOString() : c
    net.online = false
  } else if (res.config?.method === 'get') {
    net.cachedAt = null
    net.online = true
  }
}

/** 退出登录时清掉缓存的数据和图片（同一台手机可能换人用） */
export function clearOfflineData() {
  navigator.serviceWorker?.controller?.postMessage({ type: 'CLEAR_DATA' })
}
