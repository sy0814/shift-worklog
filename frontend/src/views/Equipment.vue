<script setup>
// 设备台账：设备编号、名称、区域、型号、备注（名称 / 区域 / 备注三语，只填一种会自动翻译）。
// 每台设备可以查看关联的任务；任务表单里可以选设备。
import RowActions from '../components/RowActions.vue'
import { useActionsWidth } from '../rowActions'
import { computed, onMounted, reactive, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Loading } from '@element-plus/icons-vue'
import api, { download } from '../api'
import { localText } from '../i18n'
import { useAuth } from '../stores/auth'
import { translateError } from '../apiErrors'
import TriNames from '../components/TriNames.vue'
import TaskCard from '../components/TaskCard.vue'
import TaskDetail from '../components/TaskDetail.vue'
import EquipmentStats from '../components/EquipmentStats.vue'

const { t, locale } = useI18n()
const actW = useActionsWidth(() => [t('common.edit')])
const auth = useAuth()
const canManage = computed(() => auth.can('equipment.manage'))
// 设备统计：能看本车间所有任务的人、能管设备的人（和后端 equipment_stats._check 一致）
const canStats = computed(() => auth.isAdmin || ['dept', 'all'].includes(auth.scope('task.view')) || auth.can('equipment.manage'))
const view = ref('list')
const list = ref([])
const loading = ref(false)
const q = ref('')
const showInactive = ref(false)

async function load() {
  loading.value = true
  try {
    list.value = (await api.get('/equipment', { params: { q: q.value || undefined, include_inactive: showInactive.value } })).data
  } finally {
    loading.value = false
  }
}
onMounted(load)
let qTimer = null
function onSearch() { clearTimeout(qTimer); qTimer = setTimeout(load, 300) }
const tx = (row, f) => localText(row[f], row.source_lang)
const others = (row, f) => ['zh', 'sr', 'en'].filter((l) => l !== locale.value && row[f][l] && row[f][l] !== tx(row, f).text).map((l) => row[f][l])
const pending = computed(() => list.value.some((x) => x.translation_status === 'pending'))
let pollTimer = null
function pollIfPending() { // 翻译在后台进行，几秒后再读一次
  clearTimeout(pollTimer)
  if (pending.value) pollTimer = setTimeout(async () => { await load(); pollIfPending() }, 3000)
}

// ---- 新增 / 修改 ----
const dlg = ref(false)
const form = reactive({})
const editing = ref(null)
function openEdit(row) {
  editing.value = row || null
  const flat = (f) => Object.fromEntries(['zh', 'sr', 'en'].map((l) => [`${f}_${l}`, row?.[f]?.[l] || '']))
  Object.assign(form, { code: row?.code || '', model: row?.model || '', is_active: row ? row.is_active : true,
    ...flat('name'), ...flat('area'), ...flat('note') })
  dlg.value = true
}
const tri = (f) => ({ zh: form[`${f}_zh`] || null, sr: form[`${f}_sr`] || null, en: form[`${f}_en`] || null })
const canSave = computed(() => form.code?.trim() && (form.name_zh || form.name_sr || form.name_en))
async function save() {
  const body = { code: form.code.trim(), model: form.model, is_active: form.is_active, lang: locale.value,
    name: tri('name'), area: tri('area'), note: tri('note') }
  try {
    if (editing.value) await api.patch(`/equipment/${editing.value.id}`, body, { silent: true })
    else await api.post('/equipment', body, { silent: true })
  } catch (err) {
    return ElMessage.error(translateError(err.response?.data?.detail || '', locale.value, t) || t('common.requestFailed'))
  }
  dlg.value = false
  ElMessage.success(t('common.saved'))
  await load()
  pollIfPending()
}
async function remove() {
  await ElMessageBox.confirm(t('eq.confirmDelete', { c: editing.value.code }), { type: 'warning' })
  try {
    await api.delete(`/equipment/${editing.value.id}`, { silent: true })
  } catch (err) {
    return ElMessage.error(translateError(err.response?.data?.detail || '', locale.value, t))
  }
  dlg.value = false
  load()
}

// ---- 这台设备的任务 ----
const taskDrawer = ref(false)
const cur = ref(null)
const tasks = ref([])
const detailId = ref(null)
const detailOpen = ref(false)
async function openTasks(row) {
  cur.value = row
  tasks.value = []
  taskDrawer.value = true
  tasks.value = (await api.get('/tasks', { params: { equipment_id: row.id, limit: 100 } })).data.items
}
function openTask(task) { detailId.value = task.id; detailOpen.value = true }
async function taskChanged() { if (cur.value) openTasks(cur.value); load() }

// ---- Excel 导入 / 导出 ----
const imp = reactive({ open: false, file: null, result: null, busy: false })
function pickFile(e) {
  imp.file = e.target.files[0] || null
  e.target.value = ''
  if (imp.file) runImport(true)
}
async function runImport(dry) {
  imp.busy = true
  try {
    const fd = new FormData()
    fd.append('file', imp.file)
    fd.append('lang', locale.value)
    fd.append('dry_run', dry ? 'true' : 'false')
    imp.result = (await api.post('/equipment/import/xlsx', fd, { silent: true })).data
    imp.open = true
    if (imp.result.applied) {
      ElMessage.success(t('eq.imported', { c: imp.result.created, u: imp.result.updated }))
      imp.open = false
      await load()
      pollIfPending()
    }
  } catch (err) {
    ElMessage.error(translateError(err.response?.data?.detail || '', locale.value, t) || t('common.requestFailed'))
  } finally {
    imp.busy = false
  }
}
const fileInput = ref(null)
</script>

<template>
  <div class="page">
    <div class="eq-head">
      <h1 class="page-title" style="margin: 0">{{ t('eq.title') }}</h1>
      <el-radio-group v-if="canStats" v-model="view" size="small">
        <el-radio-button value="list">{{ t('eqs.list') }}</el-radio-button>
        <el-radio-button value="stats">{{ t('eqs.title') }}</el-radio-button>
      </el-radio-group>
    </div>
    <EquipmentStats v-if="view === 'stats'" />
    <template v-else>
    <div class="toolbar">
      <span class="spacer" />
      <el-input v-model="q" :placeholder="t('eq.search')" clearable style="width: 280px" @input="onSearch" @clear="load" />
      <el-checkbox v-model="showInactive" @change="load">{{ t('eq.showInactive') }}</el-checkbox>
      <el-button @click="download('/equipment/export/xlsx', { lang: locale }, 'equipment.xlsx')">{{ t('eq.export') }}</el-button>
      <template v-if="canManage">
        <el-button :loading="imp.busy" @click="fileInput.click()">{{ t('eq.import') }}</el-button>
        <input ref="fileInput" type="file" accept=".xlsx" hidden @change="pickFile">
        <el-button type="primary" @click="openEdit(null)">{{ t('eq.add') }}</el-button>
      </template>
    </div>
    <p class="muted small">{{ t('eq.hint') }}</p>

    <el-table v-loading="loading" :data="list" size="small" border class="eqt" :empty-text="t('eq.none')">
      <el-table-column prop="code" :label="t('eq.code')" width="120" fixed>
        <template #default="{ row }"><b>{{ row.code }}</b></template>
      </el-table-column>
      <el-table-column :label="t('eq.name')" min-width="200">
        <template #default="{ row }">
          <div>{{ tx(row, 'name').text }} <el-tag v-if="!row.is_active" size="small" type="info">{{ t('eq.inactive') }}</el-tag></div>
          <div v-for="o in others(row, 'name')" :key="o" class="muted small">{{ o }}</div>
          <span v-if="row.translation_status === 'pending'" class="muted small"><el-icon class="is-loading"><Loading /></el-icon> {{ t('tr.translating') }}</span>
        </template>
      </el-table-column>
      <el-table-column :label="t('eq.area')" min-width="130">
        <template #default="{ row }">{{ tx(row, 'area').text }}</template>
      </el-table-column>
      <el-table-column prop="model" :label="t('eq.model')" min-width="110" />
      <el-table-column :label="t('eq.tasks')" width="110" align="center">
        <template #default="{ row }">
          <el-button link type="primary" @click="openTasks(row)">
            <span v-if="row.tasks_open" class="open">{{ row.tasks_open }}</span><span v-if="row.tasks_open"> / </span>{{ row.tasks_total }}
          </el-button>
        </template>
      </el-table-column>
      <el-table-column :label="t('eq.last')" width="100"><template #default="{ row }">{{ row.last_task_date?.slice(5) || '—' }}</template></el-table-column>
      <el-table-column :label="t('eq.note')" min-width="160" show-overflow-tooltip>
        <template #default="{ row }">{{ tx(row, 'note').text }}</template>
      </el-table-column>
      <el-table-column v-if="canManage" :label="t('common.actions')" :width="actW" fixed="right">
        <template #default="{ row }"><RowActions v-if="row.can_manage" :items="[{ label: t('common.edit'), type: 'primary', onClick: () => openEdit(row) }]" /></template>
      </el-table-column>
    </el-table>

    <el-dialog v-model="dlg" :title="editing ? `${t('common.edit')} · ${editing.code}` : t('eq.add')" width="min(520px, 94vw)" append-to-body>
      <el-form label-position="top" @submit.prevent>
        <el-form-item :label="t('eq.code')" required><el-input v-model="form.code" maxlength="60" /></el-form-item>
        <el-form-item :label="t('eq.name')" required><TriNames v-model="form" prefix="name_" :maxlength="200" /></el-form-item>
        <el-form-item :label="t('eq.area')"><TriNames v-model="form" prefix="area_" :maxlength="200" /></el-form-item>
        <el-form-item :label="t('eq.model')"><el-input v-model="form.model" maxlength="200" /></el-form-item>
        <el-form-item :label="t('eq.note')"><TriNames v-model="form" prefix="note_" :maxlength="1000" /></el-form-item>
        <el-form-item v-if="editing"><el-checkbox v-model="form.is_active">{{ t('eq.active') }}</el-checkbox></el-form-item>
      </el-form>
      <p class="muted small">{{ t('eq.trHint') }}</p>
      <template #footer>
        <el-button v-if="editing && !editing.tasks_total" type="danger" plain style="float: left" @click="remove">{{ t('common.delete') }}</el-button>
        <el-button @click="dlg = false">{{ t('common.cancel') }}</el-button>
        <el-button type="primary" :disabled="!canSave" @click="save">{{ t('common.save') }}</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="imp.open" :title="t('eq.import')" width="min(480px, 94vw)" append-to-body>
      <template v-if="imp.result">
        <el-alert v-if="imp.result.errors.length" type="error" :closable="false" :title="t('eq.impErrors')">
          <div v-for="e in imp.result.errors" :key="e.row">{{ t('eq.row', { n: e.row }) }}: {{ translateError(e.error, locale, t) }}</div>
        </el-alert>
        <p v-else>{{ t('eq.impPreview', { c: imp.result.created, u: imp.result.updated, s: imp.result.unchanged }) }}</p>
      </template>
      <p class="muted small">{{ t('eq.impHint') }}</p>
      <template #footer>
        <el-button @click="imp.open = false">{{ t('common.close') }}</el-button>
        <el-button v-if="imp.result && !imp.result.errors.length" type="primary" :loading="imp.busy"
                   :disabled="!imp.result.created && !imp.result.updated" @click="runImport(false)">{{ t('eq.impConfirm') }}</el-button>
      </template>
    </el-dialog>

    <el-drawer v-model="taskDrawer" :title="cur ? `${cur.code} · ${tx(cur, 'name').text}` : ''" size="min(560px, 100%)" append-to-body>
      <div v-if="cur" class="muted small mb">{{ tx(cur, 'area').text }} {{ cur.model }}</div>
      <div v-if="!tasks.length" class="muted">{{ t('eq.noTasks') }}</div>
      <TaskCard v-for="task in tasks" :key="task.id" :task="task" class="tc" @click="openTask(task)" />
    </el-drawer>
    </template>
    <TaskDetail v-model="detailOpen" :task-id="detailId" @changed="taskChanged" />
  </div>
</template>

<style scoped>
.eq-head { display: flex; align-items: center; gap: 12px; flex-wrap: wrap; margin-bottom: 8px; }
.spacer { flex: 1; }
.toolbar { display: flex; gap: 8px; align-items: center; margin-bottom: 4px; flex-wrap: wrap; }
.muted { color: #909399; }
.small { font-size: 12px; }
.mb { margin-bottom: 10px; }
.open { color: #e6a23c; font-weight: 600; }
.tc { margin-bottom: 8px; cursor: pointer; }
</style>
