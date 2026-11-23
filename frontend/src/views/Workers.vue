<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { ElMessage } from 'element-plus'
import api from '../api'
import { localName } from '../i18n'
import { useAuth } from '../stores/auth'
import WorkerAvatar from '../components/WorkerAvatar.vue'

const { t } = useI18n()
const auth = useAuth()
const rows = ref([])
const showInactive = ref(false)
const teamFilter = ref(null)

async function load() {
  rows.value = (await api.get('/workers', { params: { include_inactive: showInactive.value } })).data
}
onMounted(load)
const shown = computed(() => rows.value.filter((w) => !teamFilter.value || w.team_id === teamFilter.value))

const dialog = ref(false)
const editing = ref(null)
const form = reactive({})
function openCreate() {
  editing.value = null
  Object.assign(form, { name: '', employee_no: '', team_id: teamFilter.value, is_active: true })
  dialog.value = true
}
function openEdit(w) {
  editing.value = w
  Object.assign(form, { name: w.name, employee_no: w.employee_no || '', team_id: w.team_id, is_active: w.is_active })
  dialog.value = true
}
async function save() {
  if (editing.value) await api.patch(`/workers/${editing.value.id}`, { ...form })
  else await api.post('/workers', { name: form.name, employee_no: form.employee_no || null, team_id: form.team_id })
  dialog.value = false
  ElMessage.success(t('common.saved'))
  load()
}

// ---- 头像 ----
const avatarInput = ref()
const avatarFor = ref(null)
function pickAvatar(w) {
  avatarFor.value = w
  avatarInput.value.click()
}
async function uploadAvatar(e) {
  const f = e.target.files[0]
  e.target.value = ''
  if (!f || !avatarFor.value) return
  const fd = new FormData()
  fd.append('file', f)
  await api.post(`/workers/${avatarFor.value.id}/avatar`, fd, { timeout: 60000 })
  ElMessage.success(t('common.saved'))
  load()
}
async function removeAvatar(w) {
  await api.delete(`/workers/${w.id}/avatar`)
  ElMessage.success(t('avatar.removed'))
  load()
}

const bulkOpen = ref(false)
const bulk = reactive({ text: '', team_id: null })
async function saveBulk() {
  const names = bulk.text.split(/\r?\n/).map((s) => s.trim()).filter(Boolean)
  if (!names.length) return
  await api.post('/workers/bulk', { names, team_id: bulk.team_id })
  bulkOpen.value = false
  bulk.text = ''
  ElMessage.success(t('common.saved'))
  load()
}
</script>

<template>
  <div class="page">
    <div class="toolbar">
      <h1 class="page-title" style="margin: 0; flex: 1">{{ t('nav2.workers') }}</h1>
      <el-select v-model="teamFilter" clearable :placeholder="t('task.allTeams')" style="width: 130px">
        <el-option v-for="tm in auth.teams" :key="tm.id" :label="localName(tm)" :value="tm.id" />
      </el-select>
      <el-checkbox v-model="showInactive" @change="load">{{ t('workers.showInactive') }}</el-checkbox>
      <el-button @click="bulk.team_id = teamFilter; bulkOpen = true">{{ t('workers.bulk') }}</el-button>
      <el-button type="primary" @click="openCreate">{{ t('common.add') }}</el-button>
    </div>
    <el-table :data="shown" size="small" border>
      <el-table-column width="64" align="center">
        <template #default="{ row }"><WorkerAvatar :worker="row" :size="36" /></template>
      </el-table-column>
      <el-table-column prop="name" :label="t('workers.name')" min-width="140" />
      <el-table-column prop="employee_no" :label="t('workers.no')" width="120" />
      <el-table-column :label="t('workers.team')" width="120">
        <template #default="{ row }">{{ row.team_id ? localName(auth.teamById(row.team_id)) : t('workers.noTeam') }}</template>
      </el-table-column>
      <el-table-column :label="t('users.active')" width="80" align="center">
        <template #default="{ row }"><el-tag :type="row.is_active ? 'success' : 'info'" size="small">{{ row.is_active ? t('common.yes') : t('common.no') }}</el-tag></template>
      </el-table-column>
      <el-table-column :label="t('common.actions')" width="220">
        <template #default="{ row }">
          <el-button link type="primary" @click="openEdit(row)">{{ t('common.edit') }}</el-button>
          <el-button link type="primary" @click="pickAvatar(row)">{{ row.avatar_url ? t('avatar.change') : t('avatar.upload') }}</el-button>
          <el-button v-if="row.avatar_url" link type="danger" @click="removeAvatar(row)">{{ t('avatar.remove') }}</el-button>
        </template>
      </el-table-column>
    </el-table>

    <input ref="avatarInput" type="file" accept="image/*,.heic,.heif" hidden @change="uploadAvatar" />
    <el-dialog v-model="dialog" :title="editing ? t('common.edit') : t('common.add')" width="min(420px, 94vw)">
      <el-form label-width="auto">
        <el-form-item :label="t('workers.name')"><el-input v-model="form.name" /></el-form-item>
        <el-form-item :label="t('workers.no')"><el-input v-model="form.employee_no" /></el-form-item>
        <el-form-item :label="t('workers.team')">
          <el-select v-model="form.team_id" clearable :placeholder="t('workers.noTeam')">
            <el-option v-for="tm in auth.teams" :key="tm.id" :label="localName(tm)" :value="tm.id" />
          </el-select>
        </el-form-item>
        <el-form-item v-if="editing" :label="t('users.active')"><el-switch v-model="form.is_active" /></el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialog = false">{{ t('common.cancel') }}</el-button>
        <el-button type="primary" :disabled="!form.name?.trim()" @click="save">{{ t('common.save') }}</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="bulkOpen" :title="t('workers.bulk')" width="min(420px, 94vw)">
      <el-form label-position="top">
        <el-form-item :label="t('workers.team')">
          <el-select v-model="bulk.team_id" clearable :placeholder="t('workers.noTeam')">
            <el-option v-for="tm in auth.teams" :key="tm.id" :label="localName(tm)" :value="tm.id" />
          </el-select>
        </el-form-item>
        <el-form-item :label="t('workers.name')">
          <el-input v-model="bulk.text" type="textarea" :rows="10" :placeholder="t('workers.bulkPh')" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="bulkOpen = false">{{ t('common.cancel') }}</el-button>
        <el-button type="primary" @click="saveBulk">{{ t('common.save') }}</el-button>
      </template>
    </el-dialog>
  </div>
</template>
