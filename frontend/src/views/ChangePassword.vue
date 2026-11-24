<script setup>
// 第一次登录（默认密码）或密码被别人重设过：必须先改密码才能用系统
import { computed, reactive, ref } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { ElMessage } from 'element-plus'
import api from '../api'
import { appTitle } from '../branding'
import { useAuth } from '../stores/auth'
import LangSwitch from '../components/LangSwitch.vue'

const { t, locale } = useI18n()
const auth = useAuth()
const router = useRouter()
const route = useRoute()
const pin = computed(() => auth.user?.role_info?.login_mode === 'pin')
const min = computed(() => (pin.value ? 4 : 6))
const form = reactive({ old: auth.lastSecret || '', next: '', again: '' })
const saving = ref(false)
const err = computed(() => {
  if (!form.next) return ''
  if (form.next.length < min.value) return t('cp.tooShort', { n: min.value })
  if (form.next === form.old) return t('cp.same')
  if (form.again && form.again !== form.next) return t('cp.mismatch')
  return ''
})
async function save() {
  if (err.value || form.again !== form.next) return
  saving.value = true
  try {
    await api.post('/auth/change-password', { old_password: form.old, new_password: form.next })
    await auth.refreshMe()
    auth.lastSecret = null
    ElMessage.success(t('common.saved'))
    router.replace(route.query.next || '/')
  } finally {
    saving.value = false
  }
}
function logout() {
  auth.logout()
  router.replace({ name: 'login' })
}
</script>

<template>
  <div class="wrap">
    <el-card class="card">
      <div class="head">
        <h2>{{ appTitle(locale) }}</h2>
        <LangSwitch />
      </div>
      <el-alert type="warning" :closable="false" show-icon :title="t('cp.title')" :description="t('cp.hint', { name: auth.user?.full_name || '' })" />
      <el-form label-position="top" class="form" @submit.prevent="save">
        <el-form-item :label="t('users.oldPassword')">
          <el-input v-model="form.old" type="password" show-password autocomplete="current-password" />
        </el-form-item>
        <el-form-item :label="t('users.newPassword')" :error="err">
          <el-input v-model="form.next" type="password" show-password autocomplete="new-password" :inputmode="pin ? 'numeric' : 'text'"
                    :placeholder="`≥ ${min}`" />
        </el-form-item>
        <el-form-item :label="t('cp.again')">
          <el-input v-model="form.again" type="password" show-password autocomplete="new-password" :inputmode="pin ? 'numeric' : 'text'" />
        </el-form-item>
        <el-button type="primary" native-type="submit" size="large" :loading="saving" style="width: 100%"
                   :disabled="!form.old || !form.next || !!err || form.again !== form.next">{{ t('common.save') }}</el-button>
        <el-button link class="out" @click="logout">{{ t('nav.logout') }}</el-button>
      </el-form>
    </el-card>
  </div>
</template>

<style scoped>
.wrap { min-height: 100%; display: flex; align-items: center; justify-content: center; padding: 16px; box-sizing: border-box; }
.card { width: 100%; max-width: 420px; }
.head { display: flex; justify-content: space-between; align-items: center; margin-bottom: 10px; }
.head h2 { margin: 0; font-size: 20px; }
.form { margin-top: 14px; }
.out { margin-top: 10px; }
</style>
