<script setup>
// 术语表维护（管理员）+ 翻译服务状态
import RowActions from '../components/RowActions.vue'
import { useActionsWidth } from '../rowActions'
import { computed, onMounted, reactive, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { ElMessage, ElMessageBox } from 'element-plus'
import api from '../api'

const { t } = useI18n()
const actW = useActionsWidth(() => [t('common.edit'), t('common.delete')])
const rows = ref([])
const q = ref('')
const status = ref(null)

async function load() {
  rows.value = (await api.get('/glossary')).data
  status.value = (await api.get('/translation/status')).data
}
onMounted(load)

const shown = computed(() => {
  const k = q.value.trim().toLowerCase()
  if (!k) return rows.value
  return rows.value.filter((r) => [r.zh, r.sr, r.en, r.category, r.note].some((v) => v.toLowerCase().includes(k)))
})

const dialog = ref(false)
const editing = ref(null)
const form = reactive({})
function openEdit(row) {
  editing.value = row || null
  Object.assign(form, row ? { zh: row.zh, sr: row.sr, en: row.en, category: row.category, note: row.note }
    : { zh: '', sr: '', en: '', category: '', note: '' })
  dialog.value = true
}
async function save() {
  if (editing.value) await api.put(`/glossary/${editing.value.id}`, form)
  else await api.post('/glossary', form)
  dialog.value = false
  ElMessage.success(t('common.saved'))
  load()
}
async function remove(row) {
  await ElMessageBox.confirm(`${row.zh} / ${row.sr} / ${row.en}`, t('common.delete'), { type: 'warning' })
  await api.delete(`/glossary/${row.id}`)
  load()
}

const fileInput = ref()
async function importCsv(e) {
  const f = e.target.files[0]
  e.target.value = ''
  if (!f) return
  const fd = new FormData()
  fd.append('file', f)
  const { data } = await api.post('/glossary/import', fd)
  ElMessage.success(t('glossary.imported', data))
  load()
}
async function exportCsv() {
  const { data } = await api.get('/glossary/export', { responseType: 'blob' })
  const a = document.createElement('a')
  a.href = URL.createObjectURL(data)
  a.download = 'glossary.csv'
  a.click()
  URL.revokeObjectURL(a.href)
}
async function retryFailed() {
  await api.post('/translation/retry-failed')
  setTimeout(load, 1500)
}
</script>

<template>
  <div class="page">
    <div class="toolbar">
      <h1 class="page-title" style="margin: 0; flex: 1">{{ t('glossary.title') }} ({{ rows.length }})</h1>
      <el-input v-model="q" :placeholder="t('glossary.search')" clearable style="width: 180px" />
      <el-button @click="fileInput.click()">{{ t('glossary.import') }}</el-button>
      <el-button @click="exportCsv">{{ t('glossary.export') }}</el-button>
      <el-button type="primary" @click="openEdit(null)">{{ t('common.add') }}</el-button>
      <input ref="fileInput" type="file" accept=".csv,text/csv" hidden @change="importCsv" />
    </div>

    <el-alert v-if="status && !status.configured" type="error" :title="t('tr.notConfigured')" :closable="false" show-icon class="mb" />
    <div v-if="status" class="status mb">
      <span>{{ t('tr.model') }}: <code>{{ status.model }}</code></span>
      <el-tag v-if="status.counts.pending" type="warning">{{ t('tr.pendingN', { n: status.counts.pending }) }}</el-tag>
      <el-tag v-if="status.counts.failed" type="danger">{{ t('tr.failedN', { n: status.counts.failed }) }}</el-tag>
      <el-button v-if="status.counts.failed" size="small" @click="retryFailed">{{ t('tr.retryFailed') }}</el-button>
      <span class="muted">{{ t('glossary.hint') }}</span>
    </div>

    <el-table :data="shown" size="small" border>
      <el-table-column prop="zh" :label="t('glossary.zh')" min-width="120" />
      <el-table-column prop="sr" :label="t('glossary.sr')" min-width="160" />
      <el-table-column prop="en" :label="t('glossary.en')" min-width="160" />
      <el-table-column prop="category" :label="t('glossary.category')" width="90" />
      <el-table-column prop="note" :label="t('glossary.note')" width="100" />
      <el-table-column :label="t('common.actions')" :width="actW" fixed="right">
        <template #default="{ row }">
          <RowActions :items="[{ label: t('common.edit'), type: 'primary', onClick: () => openEdit(row) },
                               { label: t('common.delete'), type: 'danger', onClick: () => remove(row) }]" />
        </template>
      </el-table-column>
    </el-table>

    <el-dialog v-model="dialog" :title="editing ? t('common.edit') : t('common.add')" width="min(460px, 94vw)">
      <el-form label-width="auto">
        <el-form-item v-for="k in ['zh', 'sr', 'en', 'category', 'note']" :key="k" :label="t(`glossary.${k}`)">
          <el-input v-model="form[k]" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialog = false">{{ t('common.cancel') }}</el-button>
        <el-button type="primary" :disabled="!form.zh?.trim() || !form.sr?.trim() || !form.en?.trim()" @click="save">{{ t('common.save') }}</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.mb { margin-bottom: 12px; }
.status { display: flex; gap: 10px; align-items: center; flex-wrap: wrap; font-size: 13px; }
.muted { color: #909399; }
</style>
