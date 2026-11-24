<script setup>
import { appTitle } from '../branding'
import { reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { ElMessage } from 'element-plus'
import { useAuth } from '../stores/auth'
import LangSwitch from '../components/LangSwitch.vue'

const { t, locale } = useI18n()
const auth = useAuth()
const router = useRouter()
const route = useRoute()
const form = reactive({ username: '', password: '' })
const loading = ref(false)

async function submit() {
  if (!form.username || !form.password) return
  loading.value = true
  try {
    await auth.login(form.username.trim(), form.password)
    router.replace(route.query.next || '/')
  } catch {
    ElMessage.closeAll()
    ElMessage.error(t('login.failed'))
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <div class="login-wrap">
    <el-card class="login-card">
      <div class="login-head">
        <h2>{{ appTitle(locale) }}</h2>
        <LangSwitch />
      </div>
      <el-form label-position="top" @submit.prevent="submit">
        <el-form-item :label="t('login.username')">
          <el-input v-model="form.username" autocomplete="username" size="large" />
        </el-form-item>
        <el-form-item :label="t('login.password')">
          <el-input v-model="form.password" type="password" show-password autocomplete="current-password" size="large" />
        </el-form-item>
        <el-button type="primary" native-type="submit" size="large" :loading="loading" style="width: 100%">
          {{ t('login.submit') }}
        </el-button>
      </el-form>
    </el-card>
  </div>
</template>

<style scoped>
.login-wrap { min-height: 100%; display: flex; align-items: center; justify-content: center; padding: 16px; box-sizing: border-box; }
.login-card { width: 100%; max-width: 380px; }
.login-head { display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px; }
.login-head h2 { margin: 0; font-size: 20px; }
</style>
