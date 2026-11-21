<script setup>
import { computed, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { ElMessage } from 'element-plus'
import api from '../api'
import { localName } from '../i18n'
import { useAuth } from '../stores/auth'
import LangSwitch from './LangSwitch.vue'

const { t } = useI18n()
const auth = useAuth()
const router = useRouter()

const menu = computed(() => [
  { name: 'home', label: t('nav.home') },
  { name: 'schedule', label: t('nav.schedule') },
  ...(auth.isAdmin ? [{ name: 'users', label: t('nav.users') }, { name: 'audit', label: t('nav.audit') }] : []),
])

function logout() {
  auth.logout()
  router.push({ name: 'login' })
}

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
  <div class="layout">
    <header class="topbar">
      <div class="brand">{{ t('app.title') }}</div>
      <nav class="nav">
        <router-link v-for="m in menu" :key="m.name" :to="{ name: m.name }" class="nav-link">{{ m.label }}</router-link>
      </nav>
      <div class="right">
        <LangSwitch />
        <el-dropdown trigger="click">
          <span class="user">
            {{ auth.user?.full_name }}
            <small v-if="auth.myTeam">· {{ localName(auth.myTeam) }}</small>
          </span>
          <template #dropdown>
            <el-dropdown-menu>
              <el-dropdown-item @click="pwDialog = true">{{ t('nav.password') }}</el-dropdown-item>
              <el-dropdown-item divided @click="logout">{{ t('nav.logout') }}</el-dropdown-item>
            </el-dropdown-menu>
          </template>
        </el-dropdown>
      </div>
    </header>
    <main><router-view /></main>

    <el-dialog v-model="pwDialog" :title="t('nav.password')" width="min(400px, 92vw)">
      <el-form label-position="top">
        <el-form-item :label="t('users.oldPassword')"><el-input v-model="pw.old_password" type="password" show-password /></el-form-item>
        <el-form-item :label="t('users.newPassword')"><el-input v-model="pw.new_password" type="password" show-password /></el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="pwDialog = false">{{ t('common.cancel') }}</el-button>
        <el-button type="primary" :disabled="pw.new_password.length < 6" @click="changePassword">{{ t('common.save') }}</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.topbar { display: flex; align-items: center; gap: 16px; padding: 8px 16px; background: #1f2d3d; color: #fff; flex-wrap: wrap; }
.brand { font-weight: 600; font-size: 16px; }
.nav { display: flex; gap: 4px; flex: 1; flex-wrap: wrap; }
.nav-link { color: #cfd8e3; text-decoration: none; padding: 6px 10px; border-radius: 4px; }
.nav-link.router-link-exact-active { background: #2f4a66; color: #fff; }
.right { display: flex; align-items: center; gap: 12px; }
.user { color: #fff; cursor: pointer; }
.user small { color: #9fb0c3; }
</style>
