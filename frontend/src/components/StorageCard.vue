<script setup>
// 系统设置 → 存储与备份（管理员）：备份放哪、第二份放哪（另一块盘 / 网络共享 / 云盘同步文件夹）、
// 最近一次备份结果、立即备份；原图超过 N 个月自动搬到归档盘
import { onMounted, reactive, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { ElMessage } from 'element-plus'
import api from '../api'
import { translateError } from '../apiErrors'

const { t, locale } = useI18n()
const st = ref(null)
const form = reactive({ backup_dir: '', backup_copy_dir: '', archive_enabled: false, archive_months: 12, archive_dir: '' })
const checks = reactive({})
const busy = reactive({ save: false, backup: false, archive: false })

async function load() {
  st.value = (await api.get('/storage')).data
  for (const k of Object.keys(form)) form[k] = st.value[k]
}
onMounted(load)

async function check(key) {
  const path = form[key]?.trim()
  if (!path) { checks[key] = null; return }
  checks[key] = (await api.post('/storage/check', { path })).data
}
const checkText = (c) => c.ok ? t('stor.okFree', { f: c.free_gb, tot: c.total_gb }) : translateError(c.error, locale.value, t)
const err = (e) => ElMessage.error(translateError(e.response?.data?.detail || '', locale.value, t) || t('common.requestFailed'))

async function save() {
  busy.save = true
  try {
    st.value = (await api.put('/storage', { ...form }, { silent: true })).data
    ElMessage.success(t('common.saved'))
  } catch (e) { err(e) } finally { busy.save = false }
}
async function backupNow() {
  busy.backup = true
  try {
    await api.post('/storage/backup-now', null, { silent: true })
    ElMessage.success(t('stor.backupStarted'))
    setTimeout(load, 60000)
  } catch (e) { err(e) } finally { busy.backup = false }
}
async function archiveNow() {
  busy.archive = true
  try {
    const r = (await api.post('/storage/archive-now', null, { silent: true, timeout: 600000 })).data
    if (r.errors.length) ElMessage.warning(`${t('stor.archived', { n: r.moved })} · ${r.errors.slice(0, 3).map((x) => translateError(x, locale.value, t)).join('；')}`)
    else ElMessage.success(t('stor.archived', { n: r.moved }))
    await load()
  } catch (e) { err(e) } finally { busy.archive = false }
}
</script>

<template>
  <el-card v-if="st" shadow="never" class="mb">
    <template #header>{{ t('stor.title') }}</template>
    <el-form label-position="top" @submit.prevent>
      <h4>{{ t('stor.backup') }}</h4>
      <div class="last">
        <template v-if="st.status">
          <el-tag :type="st.status.ok ? 'success' : 'danger'" size="small">{{ st.status.ok ? t('stor.lastOk') : t('stor.lastFail') }}</el-tag>
          <span>{{ st.status.at }}</span>
          <span v-if="st.status.size_mb != null" class="muted">{{ t('stor.dbSize', { n: st.status.size_mb }) }}</span>
          <span v-if="st.status.free_gb != null" class="muted">{{ t('stor.free', { n: st.status.free_gb }) }}</span>
          <span v-if="st.status.message" class="err">{{ st.status.message }}</span>
          <span v-if="st.status.copy">· {{ t('stor.copy') }}:
            <el-tag :type="st.status.copy_result === 'ok' ? 'success' : 'danger'" size="small" effect="plain">{{ st.status.copy_result === 'ok' ? 'OK' : st.status.copy_result || '—' }}</el-tag>
          </span>
        </template>
        <span v-else class="muted">{{ t('stor.never') }}</span>
        <el-button size="small" :loading="busy.backup" :disabled="!st.windows" @click="backupNow">{{ t('stor.backupNow') }}</el-button>
      </div>
      <el-form-item :label="t('stor.backupDir')">
        <div class="pathrow">
          <el-input v-model="form.backup_dir" :placeholder="st.default_backup_dir" @input="checks.backup_dir = null" />
          <el-button @click="check('backup_dir')">{{ t('stor.check') }}</el-button>
        </div>
        <small :class="['chk', checks.backup_dir?.ok ? 'ok' : 'err']">{{ checks.backup_dir ? checkText(checks.backup_dir) : '' }}</small>
        <small class="muted">{{ t('stor.backupHint') }}</small>
      </el-form-item>
      <el-form-item :label="t('stor.copyDir')">
        <div class="pathrow">
          <el-input v-model="form.backup_copy_dir" :placeholder="t('stor.copyPh')" @input="checks.backup_copy_dir = null" />
          <el-button @click="check('backup_copy_dir')">{{ t('stor.check') }}</el-button>
        </div>
        <small :class="['chk', checks.backup_copy_dir?.ok ? 'ok' : 'err']">{{ checks.backup_copy_dir ? checkText(checks.backup_copy_dir) : '' }}</small>
        <small class="muted">{{ t('stor.copyHint') }}</small>
      </el-form-item>

      <h4>{{ t('stor.archive') }}</h4>
      <el-form-item>
        <el-checkbox v-model="form.archive_enabled">{{ t('stor.archiveOn') }}</el-checkbox>
        <el-input-number v-model="form.archive_months" :min="1" :max="120" size="small" class="months" />
        <span>{{ t('stor.months') }}</span>
      </el-form-item>
      <el-form-item :label="t('stor.archiveDir')">
        <div class="pathrow">
          <el-input v-model="form.archive_dir" placeholder="D:\WorkRecordArchive" @input="checks.archive_dir = null" />
          <el-button @click="check('archive_dir')">{{ t('stor.check') }}</el-button>
        </div>
        <small :class="['chk', checks.archive_dir?.ok ? 'ok' : 'err']">{{ checks.archive_dir ? checkText(checks.archive_dir) : '' }}</small>
        <small class="muted">{{ t('stor.archiveHint') }}</small>
      </el-form-item>
      <div class="last">
        <span>{{ t('stor.archStat', { a: st.archived, d: st.due }) }}</span>
        <el-button size="small" :loading="busy.archive" :disabled="!st.archive_dir || !st.due" @click="archiveNow">{{ t('stor.archiveNow') }}</el-button>
      </div>
      <el-form-item><el-button type="primary" :loading="busy.save" @click="save">{{ t('common.save') }}</el-button></el-form-item>
    </el-form>
  </el-card>
</template>

<style scoped>
.mb { margin-bottom: 16px; }
h4 { margin: 4px 0 10px; font-size: 14px; }
.last { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; margin-bottom: 14px; font-size: 13px; }
.pathrow { display: flex; gap: 8px; width: 100%; }
small { display: block; width: 100%; line-height: 1.5; margin-top: 2px; }
.muted { color: #909399; }
.ok { color: #67c23a; }
.err { color: #f56c6c; }
.chk { min-height: 1.5em; } /* 先占好位置，检查结果出现 / 消失时下面不跳 */
.months { margin: 0 8px 0 12px; width: 110px; }
</style>
