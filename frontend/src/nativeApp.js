// 在安卓 App（mobile/，Capacitor 外壳）里打开时：User-Agent 带「WorkRecordApp/版本号」
import api from './api'

const m = navigator.userAgent.match(/WorkRecordApp\/([\w.-]+)/)
export const appVersion = m ? m[1] : null
export const inApp = !!appVersion

// App 自己的「填服务器地址」页（打包在 App 里，Capacitor 本地地址）
export function openAppSetup() {
  location.href = 'https://localhost/index.html?setup=1'
}

// 服务器上有更新的 App 时返回新版本号（没有 / 不在 App 里 = null）
export async function newerAppVersion() {
  if (!inApp) return null
  try {
    const { data } = await api.get('/app-info', { silent: true })
    return data.version && data.version !== appVersion ? data.version : null
  } catch {
    return null
  }
}
