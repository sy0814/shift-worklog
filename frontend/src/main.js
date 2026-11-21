import { createApp } from 'vue'
import { createPinia } from 'pinia'
import ElementPlus from 'element-plus'
import 'element-plus/dist/index.css'
import App from './App.vue'
import router from './router'
import { i18n, setLang } from './i18n'
import './style.css'

setLang(i18n.global.locale.value)

createApp(App).use(createPinia()).use(router).use(i18n).use(ElementPlus).mount('#app')
