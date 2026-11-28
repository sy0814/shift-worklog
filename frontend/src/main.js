import { createApp } from 'vue'
import { createPinia } from 'pinia'
import ElementPlus, { ElButton, ElNotification } from 'element-plus'
import { h } from 'vue'
import 'element-plus/dist/index.css'
import App from './App.vue'
import router from './router'
import { i18n, personName, setLang } from './i18n'
import './style.css'

setLang(i18n.global.locale.value)

const app = createApp(App).use(createPinia()).use(router).use(i18n).use(ElementPlus)
app.config.globalProperties.$pn = personName // 模板里显示人名用 $pn(name)：自带管理员跟着语言显示
app.mount('#app')

// PWA：注册 Service Worker；有新版本时提示，由用户点「刷新」（避免冲掉正在填的表单）
if ('serviceWorker' in navigator && import.meta.env.PROD) {
  import('virtual:pwa-register').then(({ registerSW }) => {
    const updateSW = registerSW({
      onNeedRefresh() {
        const t = i18n.global.t
        const n = ElNotification({
          title: t('pwa.newVersion'), duration: 0, type: 'info',
          message: h('div', [h('span', t('pwa.newVersionHint') + ' '),
            h(ElButton, { size: 'small', type: 'primary', onClick: () => { n.close(); updateSW(true) } }, () => t('pwa.reload'))]),
        })
      },
    })
  })
}
