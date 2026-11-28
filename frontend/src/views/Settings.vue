<script setup>
// 系统设置（管理员）：系统名称、AI 接口、未闭环警示
import { computed, onMounted, reactive, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { ElMessage, ElMessageBox } from 'element-plus'
import api from '../api'
import TriNames from '../components/TriNames.vue'
import StorageCard from '../components/StorageCard.vue'
import ServerAddressCard from '../components/ServerAddressCard.vue'
import DepartmentsCard from '../components/DepartmentsCard.vue'
import { LANGS, i18n } from '../i18n'
import { branding, loadBranding } from '../branding'

const { t } = useI18n()

// ---------------- AI 接口 ----------------
const cur = ref(null) // 服务器上当前生效的
const form = reactive({ provider: 'deepseek', base_url: '', translate_model: '', analysis_model: '', api_key: '' })
const models = ref([])
const busy = reactive({ test: false, save: false, models: false })
const testResult = ref(null)

async function loadLLM() {
  cur.value = (await api.get('/settings/llm')).data
  Object.assign(form, {
    provider: cur.value.provider, base_url: cur.value.base_url, translate_model: cur.value.translate_model,
    analysis_model: cur.value.analysis_model, api_key: '',
  })
  models.value = []
  testResult.value = null
}

const host = (u) => { try { return new URL(u).hostname } catch { return '' } }
// 换了接口地址就必须填新 Key（服务器同样会拦）
const needKey = computed(() => cur.value && host(form.base_url) !== host(cur.value.base_url) && !form.api_key.trim())

function changeProvider(p) {
  const preset = cur.value.presets[p]
  form.base_url = preset.base_url
  form.translate_model = preset.translate_model
  form.analysis_model = preset.analysis_model
  models.value = []
  testResult.value = null
}

const payload = () => ({ ...form, api_key: form.api_key.trim() || null })

async function fetchModels() {
  busy.models = true
  try {
    models.value = (await api.post('/settings/llm/models', payload())).data
    ElMessage.success(t('sys.models', { n: models.value.length }))
  } finally {
    busy.models = false
  }
}
async function test() {
  busy.test = true
  testResult.value = null
  try {
    testResult.value = (await api.post('/settings/llm/test', payload(), { timeout: 90000 })).data
  } finally {
    busy.test = false
  }
}
async function save() {
  busy.save = true
  try {
    cur.value = (await api.put('/settings/llm', payload())).data
    form.api_key = ''
    ElMessage.success(t('common.saved'))
  } finally {
    busy.save = false
  }
}
async function reset() {
  await ElMessageBox.confirm(t('sys.confirmReset'), t('sys.reset'), { type: 'warning' })
  cur.value = (await api.delete('/settings/llm')).data
  await loadLLM()
  ElMessage.success(t('common.saved'))
}

// ---------------- 系统名称 ----------------
const nameForm = reactive({ zh: '', sr: '', en: '' })
const defaultName = (l) => i18n.global.t('app.title', {}, { locale: l })
// 新员工默认密码（只有管理员能看、能改）
const dp = ref('')
async function loadDp() { try { dp.value = (await api.get('/users/default-password', { silent: true })).data.password } catch { /* 不是管理员 */ } }
async function saveDp() {
  dp.value = (await api.put('/users/default-password', { password: dp.value.trim() })).data.password
  ElMessage.success(t('common.saved'))
}
async function saveName() {
  Object.assign(branding, (await api.put('/branding', nameForm)).data)
  ElMessage.success(t('common.saved'))
}

// ---------------- 未闭环警示 ----------------
const alertCfg = reactive({ overdue_hours: 24, overdue_handovers: 3 })
async function saveAlert() {
  Object.assign(alertCfg, (await api.put('/settings', alertCfg)).data)
  ElMessage.success(t('common.saved'))
}

onMounted(async () => {
  loadDp()
  await loadBranding()
  Object.assign(nameForm, branding)
  await loadLLM()
  Object.assign(alertCfg, (await api.get('/settings')).data)
})
</script>

<template>
  <div class="page">
    <h1 class="page-title">{{ t('sys.title') }}</h1>
    <el-card shadow="never" class="mb">
      <template #header><b>{{ t('sys.appName') }}</b></template>
      <el-form label-width="auto" style="max-width: 520px">
        <el-form-item :label="t('sys.appName')">
          <TriNames v-model="nameForm" prefix="" :maxlength="100" :placeholders="{ zh: defaultName('zh'), sr: defaultName('sr'), en: defaultName('en') }" />
        </el-form-item>
        <el-form-item><span class="muted">{{ t('sys.appNameHint', { def: defaultName($i18n.locale) }) }}</span></el-form-item>
        <el-form-item><el-button type="primary" @click="saveName">{{ t('common.save') }}</el-button></el-form-item>
      </el-form>
    </el-card>

    <DepartmentsCard />

    <!-- 新员工默认密码 -->
    <el-card shadow="never" class="mb">
      <template #header>{{ t('dp.title') }}</template>
      <el-form label-width="auto" style="max-width: 520px" @submit.prevent>
        <el-form-item :label="t('dp.label')">
          <el-input v-model="dp" maxlength="50" style="width: 220px" />
        </el-form-item>
        <el-form-item><span class="muted">{{ t('dp.hint') }}</span></el-form-item>
        <el-form-item><el-button type="primary" :disabled="dp.trim().length < 6" @click="saveDp">{{ t('common.save') }}</el-button></el-form-item>
      </el-form>
    </el-card>

    <!-- 存储与备份 -->
    <StorageCard />
    <ServerAddressCard />

    <el-card v-if="cur" shadow="never" class="mb">
      <template #header>
        <div class="hdr">
          <b>{{ t('sys.ai') }}</b>
          <span class="muted">{{ t('sys.source') }}：{{ cur.source === 'db' ? t('sys.srcDb') : t('sys.srcEnv') }} ·
            <code>{{ cur.translate_model }}</code> @ {{ host(cur.base_url) }}</span>
        </div>
      </template>
      <el-alert :title="t('sys.fixedNote')" type="info" :closable="false" show-icon class="mb" />
      <el-form label-width="auto" label-position="left" style="max-width: 640px">
        <el-form-item :label="t('sys.provider')">
          <el-radio-group v-model="form.provider" @change="changeProvider">
            <el-radio-button value="deepseek">{{ t('sys.deepseek') }}</el-radio-button>
            <el-radio-button value="openai_compatible">{{ t('sys.other') }}</el-radio-button>
          </el-radio-group>
        </el-form-item>
        <el-form-item :label="t('sys.baseUrl')">
          <el-input v-model="form.base_url" placeholder="https://api.example.com/v1" />
        </el-form-item>
        <el-form-item :label="t('sys.apiKey')" :error="needKey ? t('sys.keyRequired') : ''">
          <el-input v-model="form.api_key" type="password" show-password autocomplete="new-password"
                    :placeholder="!cur.api_key_set ? t('sys.keyNone') : cur.source === 'env' ? t('sys.keyEnv', { hint: cur.api_key_hint }) : t('sys.keySet', { hint: cur.api_key_hint })" />
        </el-form-item>
        <el-form-item :label="t('sys.translateModel')">
          <div class="row">
            <el-select v-model="form.translate_model" filterable allow-create default-first-option style="flex: 1">
              <el-option v-for="m in models" :key="m" :label="m" :value="m" />
            </el-select>
            <el-button :loading="busy.models" :disabled="needKey" @click="fetchModels">{{ t('sys.fetchModels') }}</el-button>
          </div>
        </el-form-item>
        <el-form-item :label="t('sys.analysisModel')">
          <el-select v-model="form.analysis_model" filterable allow-create default-first-option style="width: 100%">
            <el-option v-for="m in models" :key="m" :label="m" :value="m" />
          </el-select>
        </el-form-item>
        <el-form-item>
          <div class="btns">
            <el-button :loading="busy.test" :disabled="needKey || !form.translate_model" @click="test">{{ t('sys.test') }}</el-button>
            <el-button type="primary" :loading="busy.save" :disabled="needKey || !form.translate_model" @click="save">{{ t('sys.save') }}</el-button>
            <el-button v-if="cur.source === 'db'" type="danger" plain @click="reset">{{ t('sys.reset') }}</el-button>
            <span class="muted">{{ t('sys.saveHint') }}</span>
          </div>
        </el-form-item>
      </el-form>

      <div v-if="busy.test" class="muted">{{ t('sys.testing') }}</div>
      <el-alert v-if="testResult && testResult.ok" type="success" :closable="false" show-icon
                :title="`${t('sys.testOk', { ms: testResult.latency_ms })} · ${testResult.model}`">
        <div class="sample">
          <div>zh：{{ testResult.zh }}</div>
          <div>sr：{{ testResult.sr }}</div>
          <div>en：{{ testResult.en }}</div>
        </div>
      </el-alert>
      <el-alert v-if="testResult && !testResult.ok" type="error" :closable="false" show-icon
                :title="t('sys.testFail')" :description="testResult.error" />
    </el-card>

    <el-card shadow="never">
      <template #header><b>{{ t('overdue.settings') }}</b></template>
      <el-form label-width="auto" label-position="left" style="max-width: 520px">
        <el-form-item :label="t('overdue.hoursLabel')"><el-input-number v-model="alertCfg.overdue_hours" :min="1" :max="1440" /></el-form-item>
        <el-form-item :label="t('overdue.handoversLabel')"><el-input-number v-model="alertCfg.overdue_handovers" :min="1" :max="100" /></el-form-item>
        <el-form-item><span class="muted">{{ t('overdue.hint') }}</span></el-form-item>
        <el-form-item><el-button type="primary" @click="saveAlert">{{ t('common.save') }}</el-button></el-form-item>
      </el-form>
    </el-card>
  </div>
</template>

<style scoped>
.mb { margin-bottom: 12px; }
.hdr { display: flex; gap: 12px; align-items: baseline; flex-wrap: wrap; }
.muted { color: #909399; font-size: 13px; }
.row { display: flex; gap: 8px; width: 100%; }
.btns { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }
.btns .el-button + .el-button { margin-left: 0; }
.sample { font-size: 13px; line-height: 1.7; margin-top: 4px; }
code { background: #f4f4f5; padding: 1px 4px; border-radius: 3px; }
</style>
