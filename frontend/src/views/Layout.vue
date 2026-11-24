<script setup>
import { appTitle } from '../branding'
// 布局：电脑 = 顶部导航（管理类页面收进「管理」下拉）；手机 = 精简顶栏 + 底部标签栏 + 抽屉菜单
import { computed, onMounted, onUnmounted, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { ElMessage } from 'element-plus'
import { ArrowDown, Calendar, Clock, Document, House, Menu } from '@element-plus/icons-vue'
import dayjs from 'dayjs'
import api from '../api'
import { LANGS, localName } from '../i18n'
import { net } from '../net'
import { useAuth } from '../stores/auth'
import LangSwitch from '../components/LangSwitch.vue'
import OutboxButton from '../components/OutboxButton.vue'

const { t, locale } = useI18n()
const auth = useAuth()
const router = useRouter()
const route = useRoute()

// 窄屏判断（随窗口大小 / 横竖屏变化）
const narrow = ref(window.innerWidth < 768)
const onResize = () => { narrow.value = window.innerWidth < 768 }
onMounted(() => window.addEventListener('resize', onResize))
onUnmounted(() => window.removeEventListener('resize', onResize))

const main = computed(() => [
  { name: 'home', label: t('nav.home'), icon: House },
  { name: 'tasks', label: t('nav2.tasks'), icon: Document },
  { name: 'attendance', label: t('att.title'), icon: Calendar },
  { name: 'schedule', label: t('nav.schedule'), icon: Clock },
  ...(!auth.isAdmin && auth.can('inspection.manage') ? [{ name: 'inspections', label: t('insp.title') }] : []), // 管理员的在「管理」里
  ...(!auth.isAdmin && auth.can('worker.pin') ? [{ name: 'workers', label: t('nav2.workers') }] : []), // 班长：给成员重设个人密码
])
const admin = computed(() => auth.isAdmin ? [
  { name: 'workers', label: t('nav2.workers') }, { name: 'glossary', label: t('nav2.glossary') },
  { name: 'inspections', label: t('insp.title') }, { name: 'analysis', label: t('ai.title') }, { name: 'roles', label: t('rp.title') }, { name: 'users', label: t('nav.users') }, { name: 'audit', label: t('nav.audit') }, { name: 'settings', label: t('sys.title') },
] : [])
const tabs = computed(() => main.value.slice(0, 4)) // 手机底部标签栏
const adminActive = computed(() => admin.value.some((m) => m.name === route.name))

const drawer = ref(false)
watch(() => route.fullPath, () => { drawer.value = false })
function go(name) { router.push({ name }) }

function logout() {
  auth.logout()
  router.push({ name: 'login' })
}
// 班组账号（共用手机）：30 分钟没操作自动退出，下一个人点自己的头像登录
const teamLogin = computed(() => auth.user?.role_info?.login_mode === 'pin')
let lastActive = Date.now()
const touch = () => { lastActive = Date.now() }
let idleTimer
onMounted(() => {
  ;['pointerdown', 'keydown'].forEach((ev) => window.addEventListener(ev, touch, { passive: true }))
  idleTimer = setInterval(() => { if (teamLogin.value && Date.now() - lastActive > 30 * 60 * 1000) logout() }, 60 * 1000)
})
onUnmounted(() => {
  ;['pointerdown', 'keydown'].forEach((ev) => window.removeEventListener(ev, touch))
  clearInterval(idleTimer)
})
const roleName = computed(() => auth.roleName(locale.value))

const pwDialog = ref(false)
const pw = reactive({ old_password: '', new_password: '' })
async function changePassword() {
  await api.post('/auth/change-password', pw)
  ElMessage.success(t('common.saved'))
  pwDialog.value = false
  pw.old_password = pw.new_password = ''
}
</script>

<template>
  <div :class="['layout', { narrow }]">
    <header class="topbar">
      <div class="brand">{{ appTitle(locale) }}</div>
      <nav v-if="!narrow" class="nav">
        <router-link v-for="m in main" :key="m.name" :to="{ name: m.name }" class="nav-link">{{ m.label }}</router-link>
        <el-dropdown v-if="admin.length" trigger="click" @command="go">
          <span :class="['nav-link', 'dd', { active: adminActive }]">{{ t('menu.admin') }} <el-icon><ArrowDown /></el-icon></span>
          <template #dropdown>
            <el-dropdown-menu>
              <el-dropdown-item v-for="m in admin" :key="m.name" :command="m.name">{{ m.label }}</el-dropdown-item>
            </el-dropdown-menu>
          </template>
        </el-dropdown>
      </nav>
      <div class="right">
        <OutboxButton />
        <template v-if="!narrow">
          <LangSwitch />
          <el-dropdown trigger="click">
            <span class="user">
              {{ auth.user?.full_name }}
              <small v-if="auth.myTeam">· {{ localName(auth.myTeam) }}<template v-if="roleName"> · {{ roleName }}</template></small>
            </span>
            <template #dropdown>
              <el-dropdown-menu>
                <el-dropdown-item @click="pwDialog = true">{{ t('nav.password') }}</el-dropdown-item>
                <el-dropdown-item v-if="teamLogin" divided @click="logout">{{ t('users.switchUser') }}</el-dropdown-item>
                <el-dropdown-item :divided="!teamLogin" @click="logout">{{ t('nav.logout') }}</el-dropdown-item>
              </el-dropdown-menu>
            </template>
          </el-dropdown>
        </template>
        <button v-else class="menu-btn" :aria-label="t('menu.more')" @click="drawer = true"><el-icon :size="22"><Menu /></el-icon></button>
      </div>
    </header>

    <div v-if="!net.online" class="offline-bar">
      {{ net.cachedAt ? t('pwa.offlineData', { time: dayjs(net.cachedAt).format('MM-DD HH:mm') }) : t('pwa.offlineNoData') }}
    </div>

    <main><router-view /></main>

    <!-- 手机：底部标签栏 -->
    <nav v-if="narrow" class="tabbar">
      <router-link v-for="m in tabs" :key="m.name" :to="{ name: m.name }" class="tab">
        <el-icon :size="20"><component :is="m.icon" /></el-icon>
        <span>{{ m.label }}</span>
      </router-link>
      <button :class="['tab', { 'router-link-exact-active': drawer }]" @click="drawer = true">
        <el-icon :size="20"><Menu /></el-icon><span>{{ t('menu.more') }}</span>
      </button>
    </nav>

    <!-- 手机：抽屉菜单 -->
    <el-drawer v-model="drawer" direction="rtl" size="78%" :with-header="false" append-to-body>
      <div class="drawer">
        <div class="who">
          <b>{{ auth.user?.full_name }}</b>
          <span v-if="auth.myTeam" class="muted">{{ localName(auth.myTeam) }}<template v-if="roleName"> · {{ roleName }}</template></span>
        </div>
        <div class="langs">
          <el-radio-group :model-value="locale" size="small" @change="auth.changeLang">
            <el-radio-button v-for="l in LANGS" :key="l.code" :value="l.code">{{ l.label }}</el-radio-button>
          </el-radio-group>
        </div>
        <div class="links">
          <router-link v-for="m in [...main, ...admin]" :key="m.name" :to="{ name: m.name }" class="dlink">{{ m.label }}</router-link>
        </div>
        <div class="links">
          <a class="dlink" @click="pwDialog = true; drawer = false">{{ t('nav.password') }}</a>
          <a v-if="teamLogin" class="dlink" @click="logout">{{ t('users.switchUser') }}</a>
          <a class="dlink danger" @click="logout">{{ t('nav.logout') }}</a>
        </div>
      </div>
    </el-drawer>

    <el-dialog v-model="pwDialog" :title="t('nav.password')" width="min(400px, 92vw)" append-to-body>
      <el-form label-position="top">
        <el-form-item :label="t('users.oldPassword')"><el-input v-model="pw.old_password" type="password" show-password /></el-form-item>
        <el-form-item :label="t('users.newPassword')"><el-input v-model="pw.new_password" type="password" show-password /></el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="pwDialog = false">{{ t('common.cancel') }}</el-button>
        <el-button type="primary" :disabled="pw.new_password.length < (teamLogin ? 4 : 6)" @click="changePassword">{{ t('common.save') }}</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.topbar {
  display: flex; align-items: center; gap: 16px; background: #1f2d3d; color: #fff;
  padding: 8px 16px; padding-top: calc(8px + env(safe-area-inset-top));
  position: sticky; top: 0; z-index: 20;
}
.brand { font-weight: 600; font-size: 16px; white-space: nowrap; }
.nav { display: flex; gap: 4px; flex: 1; flex-wrap: wrap; align-items: center; }
.nav-link { color: #cfd8e3; text-decoration: none; padding: 6px 10px; border-radius: 4px; cursor: pointer; display: inline-flex; align-items: center; gap: 2px; font-size: 14px; }
.nav-link.router-link-exact-active, .nav-link.active { background: #2f4a66; color: #fff; }
.right { display: flex; align-items: center; gap: 12px; margin-left: auto; }
.user { color: #fff; cursor: pointer; white-space: nowrap; }
.user small { color: #9fb0c3; }
.menu-btn { background: none; border: 0; color: #fff; padding: 4px; display: flex; cursor: pointer; }

.offline-bar { background: #fdf6ec; color: #b88230; font-size: 13px; padding: 6px 16px; border-bottom: 1px solid #faecd8; }

.narrow main { padding-bottom: calc(60px + env(safe-area-inset-bottom)); }
.tabbar {
  position: fixed; left: 0; right: 0; bottom: 0; z-index: 20; display: flex; background: #fff;
  border-top: 1px solid #e4e7ed; padding-bottom: env(safe-area-inset-bottom);
}
.tab {
  flex: 1; display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 2px;
  height: 56px; color: #909399; font-size: 11px; text-decoration: none; background: none; border: 0; cursor: pointer;
  min-width: 0;
}
.tab span { max-width: 100%; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; padding: 0 2px; }
.tab.router-link-exact-active { color: #409eff; }

.drawer { display: flex; flex-direction: column; gap: 16px; padding-top: env(safe-area-inset-top); }
.who { display: flex; flex-direction: column; gap: 2px; font-size: 16px; }
.muted { color: #909399; font-size: 13px; }
.links { display: flex; flex-direction: column; border-top: 1px solid #ebeef5; }
.dlink { padding: 14px 4px; color: #303133; text-decoration: none; border-bottom: 1px solid #f2f3f5; font-size: 15px; cursor: pointer; }
.dlink.router-link-exact-active { color: #409eff; font-weight: 600; }
.dlink.danger { color: #f56c6c; }
</style>
