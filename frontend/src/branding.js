// 系统名称：管理员在「系统设置」里可改（三种语言，没填的语言用默认名称）
import { reactive } from 'vue'
import api from './api'
import { i18n } from './i18n'

export const branding = reactive({ zh: '', sr: '', en: '' })

export async function loadBranding() {
  try {
    Object.assign(branding, (await api.get('/branding', { silent: true })).data)
  } catch { /* 断网时用默认名称 */ }
}

/** 当前语言的系统名称 */
export function appTitle(lang = i18n.global.locale.value) {
  return branding[lang] || i18n.global.t('app.title')
}
