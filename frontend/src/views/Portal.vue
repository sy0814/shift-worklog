<script setup>
// 全厂导航页：列出所有在用的车间和此刻在班的班组，点一个进入（没登录就去登录页，登录页只列这个车间的班组账号）。
// 只有一个车间时不会用到这个页面。
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import api from '../api'
import { appTitle } from '../branding'
import { getDept } from '../dept'
import { localName } from '../i18n'
import { useAuth } from '../stores/auth'
import LangSwitch from '../components/LangSwitch.vue'
import ShiftTag from '../components/ShiftTag.vue'

const { t, locale } = useI18n()
const auth = useAuth()
const router = useRouter()

const data = ref(null)
const loading = ref(true)
async function load() {
  try {
    data.value = (await api.get('/departments', { silent: true })).data
  } finally {
    loading.value = false
  }
}
let timer
onMounted(() => {
  load()
  timer = setInterval(load, 60 * 1000)
})
onUnmounted(() => clearInterval(timer))

const deps = computed(() => (data.value?.departments || []).filter((d) => d.is_active))
const last = getDept()

async function enter(d) {
  const loggedIn = !!localStorage.getItem('token') && (await auth.restore())
  if (loggedIn && auth.user.department_id !== d.id && !auth.canSwitchDept) {
    auth.logout() // 别的车间的账号：退出后用那个车间的账号登录
  }
  auth.setDept(d.id)
  if (auth.user) {
    router.push('/')
  } else {
    router.push({ name: 'login' })
  }
}
</script>

<template>
  <div class="portal">
    <header class="head">
      <h1>{{ appTitle(locale) }}</h1>
      <LangSwitch />
    </header>
    <p class="sub">{{ t('dept.choose') }}</p>
    <div v-loading="loading" class="grid">
      <button v-for="d in deps" :key="d.id" type="button" :class="['card', { last: d.id === last }]" @click="enter(d)">
        <div class="name">{{ localName(d) }}</div>
        <div v-if="d.on_duty_teams.length" class="duty">
          <ShiftTag :kind="data.shift_kind" />
          <span>{{ d.on_duty_teams.map((x) => localName(x)).join(' + ') }}</span>
        </div>
        <div v-else class="duty muted">{{ d.teams ? t('shift.off') : t('dept.noTeams') }}</div>
        <div class="foot">
          <span class="muted">{{ t('dept.teams', { n: d.teams }) }}</span>
          <span class="go">{{ t('dept.enter') }} →</span>
        </div>
      </button>
    </div>
  </div>
</template>

<style scoped>
.portal { max-width: 960px; margin: 0 auto; padding: 24px 16px calc(24px + env(safe-area-inset-bottom)); box-sizing: border-box; }
.head { display: flex; align-items: center; justify-content: space-between; gap: 12px; }
.head h1 { margin: 0; font-size: 22px; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.sub { color: #606266; margin: 8px 0 16px; }
.grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(240px, 1fr)); gap: 14px; min-height: 120px; }
.card {
  display: flex; flex-direction: column; gap: 10px; text-align: left; padding: 18px; border-radius: 10px;
  border: 1px solid #e4e7ed; background: #fff; cursor: pointer; font-family: inherit; font-size: 14px;
  transition: border-color .15s, box-shadow .15s;
}
.card:hover { border-color: #409eff; box-shadow: 0 2px 10px rgba(64, 158, 255, .15); }
.card.last { border-color: #a0cfff; }
.name { font-size: 18px; font-weight: 600; color: #303133; }
.duty { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; min-height: 24px; }
.foot { display: flex; justify-content: space-between; align-items: center; margin-top: auto; }
.go { color: #409eff; }
.muted { color: #909399; }
</style>
