<script setup>
// 账号（管理员）：列出所有登录账号；这里只新建系统管理员账号。
// 名册里的人（班长、成员……）的账号在「员工名册 → 账号」里开，姓名、班组、角色以名册为准。
import { computed, onMounted, reactive, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { ElMessage, ElMessageBox } from 'element-plus'
import dayjs from 'dayjs'
import api from '../api'
import { LANGS, localName } from '../i18n'
import { useAuth } from '../stores/auth'

const { t } = useI18n()
const auth = useAuth()
const users = ref([])
const workers = ref([])

async function load() {
  const [u, w] = await Promise.all([api.get('/users'), api.get('/workers', { params: { include_inactive: true } })])
  users.value = u.data
  workers.value = w.data
}
onMounted(load)
const workerName = (id) => workers.value.find((w) => w.id === id)?.name || ''
const isLocked = (u) => u.locked_until && dayjs(u.locked_until).isAfter(dayjs())
const admins = computed(() => users.value.filter((u) => u.role === 'admin'))
const staff = computed(() => users.value.filter((u) => u.role !== 'admin'))

// ---- 新建系统管理员 ----
const dialog = ref(false)
const form = reactive({})
function openCreate() {
  Object.assign(form, { username: '', password: '', full_name: '', lang: 'zh' })
  dialog.value = true
}
async function save() {
  await api.post('/users', { ...form })
  dialog.value = false
  ElMessage.success(t('common.saved'))
  load()
}
async function toggleActive(u) {
  await api.patch(`/users/${u.id}`, { is_active: !u.is_active })
  load()
}
async function resetPassword(u) {
  const { value } = await ElMessageBox.prompt(t('users.newPassword'), `${t('users.resetPassword')} · ${u.full_name}`, {
    inputType: 'password', inputPattern: /^.{4,}$/, inputErrorMessage: '≥ 4',
  })
  await api.post(`/users/${u.id}/reset-password`, { password: value })
  ElMessage.success(t('common.saved'))
  load()
}
async function unlock(u) {
  await api.post(`/users/${u.id}/unlock`)
  ElMessage.success(t('common.saved'))
  load()
}
// 改关联到名册里的另一个人（升级时自动建的名册记录不对时用）
const relinkOpen = ref(false)
const relink = reactive({ user: null, worker_id: null })
function openRelink(u) {
  Object.assign(relink, { user: u, worker_id: u.worker_id })
  relinkOpen.value = true
}
async function saveRelink() {
  await api.put(`/users/${relink.user.id}/worker`, { worker_id: relink.worker_id })
  relinkOpen.value = false
  ElMessage.success(t('common.saved'))
  load()
}
const freeWorkers = computed(() => workers.value.filter((w) => !users.value.some((u) => u.worker_id === w.id && u.id !== relink.user?.id)))
</script>

<template>
  <div class="page">
    <div class="toolbar">
      <h1 class="page-title" style="margin: 0; flex: 1">{{ t('nav.users') }}</h1>
      <el-button type="primary" @click="openCreate">{{ t('users.addAdmin') }}</el-button>
    </div>
    <p class="muted small">{{ t('users.hint') }}</p>

    <h3>{{ t('users.admins') }}</h3>
    <el-table :data="admins" size="small" border>
      <el-table-column prop="username" :label="t('users.username')" min-width="120" />
      <el-table-column prop="full_name" :label="t('users.fullName')" min-width="120" />
      <el-table-column :label="t('users.lastLogin')" width="150"><template #default="{ row }">{{ row.last_login_at ? dayjs(row.last_login_at).format('MM-DD HH:mm') : '—' }}</template></el-table-column>
      <el-table-column :label="t('common.actions')" width="220">
        <template #default="{ row }">
          <el-button link type="primary" @click="resetPassword(row)">{{ t('users.resetPassword') }}</el-button>
          <el-button v-if="row.id !== auth.user?.id" link :type="row.is_active ? 'danger' : 'success'" @click="toggleActive(row)">{{ row.is_active ? t('acc.disable') : t('acc.enable') }}</el-button>
        </template>
      </el-table-column>
    </el-table>

    <h3>{{ t('users.staff') }}</h3>
    <el-table :data="staff" size="small" border>
      <el-table-column :label="t('users.worker')" min-width="140">
        <template #default="{ row }"><b>{{ workerName(row.worker_id) || row.full_name }}</b></template>
      </el-table-column>
      <el-table-column :label="t('users.username')" min-width="120">
        <template #default="{ row }"><span v-if="!/^w\d+$/.test(row.username)">{{ row.username }}</span><span v-else class="muted">{{ t('acc.teamLogin') }}</span></template>
      </el-table-column>
      <el-table-column :label="t('users.team')" width="100"><template #default="{ row }">{{ localName(auth.teamById(row.team_id)) }}</template></el-table-column>
      <el-table-column :label="t('users.status')" width="120">
        <template #default="{ row }">
          <el-tag v-if="isLocked(row)" type="danger" size="small">{{ t('acc.locked') }}</el-tag>
          <el-tag v-else-if="!row.is_active" type="info" size="small">{{ t('acc.disabled') }}</el-tag>
          <el-tag v-else type="success" size="small">{{ t('acc.active') }}</el-tag>
          <el-tag v-if="row.must_change_password" type="warning" size="small" effect="plain">{{ t('dp.mustChange') }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column :label="t('users.lastLogin')" width="130"><template #default="{ row }">{{ row.last_login_at ? dayjs(row.last_login_at).format('MM-DD HH:mm') : '—' }}</template></el-table-column>
      <el-table-column :label="t('common.actions')" width="290">
        <template #default="{ row }">
          <el-button link type="primary" @click="resetPassword(row)">{{ t('users.resetPassword') }}</el-button>
          <el-button v-if="isLocked(row)" link type="warning" @click="unlock(row)">{{ t('acc.unlock') }}</el-button>
          <el-button link @click="openRelink(row)">{{ t('users.relink') }}</el-button>
          <el-button link :type="row.is_active ? 'danger' : 'success'" @click="toggleActive(row)">{{ row.is_active ? t('acc.disable') : t('acc.enable') }}</el-button>
        </template>
      </el-table-column>
    </el-table>

    <el-dialog v-model="dialog" :title="t('users.addAdmin')" width="min(420px, 94vw)" append-to-body>
      <el-form label-position="top">
        <el-form-item :label="t('users.username')"><el-input v-model="form.username" /></el-form-item>
        <el-form-item :label="t('users.password')"><el-input v-model="form.password" type="password" show-password /></el-form-item>
        <el-form-item :label="t('users.fullName')"><el-input v-model="form.full_name" /></el-form-item>
        <el-form-item :label="t('users.lang')">
          <el-select v-model="form.lang"><el-option v-for="l in LANGS" :key="l.code" :label="l.label" :value="l.code" /></el-select>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialog = false">{{ t('common.cancel') }}</el-button>
        <el-button type="primary" :disabled="!form.username || form.password.length < 6 || !form.full_name" @click="save">{{ t('common.save') }}</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="relinkOpen" :title="t('users.relink')" width="min(420px, 94vw)" append-to-body>
      <p class="muted small">{{ t('users.relinkHint') }}</p>
      <el-select v-model="relink.worker_id" filterable style="width: 100%">
        <el-option v-for="w in freeWorkers" :key="w.id" :label="`${w.name} · ${localName(auth.teamById(w.team_id)) || ''}`" :value="w.id" />
      </el-select>
      <template #footer>
        <el-button @click="relinkOpen = false">{{ t('common.cancel') }}</el-button>
        <el-button type="primary" :disabled="!relink.worker_id" @click="saveRelink">{{ t('common.save') }}</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.toolbar { display: flex; gap: 8px; align-items: center; margin-bottom: 4px; }
.muted { color: #909399; }
.small { font-size: 12px; }
h3 { margin: 16px 0 8px; font-size: 15px; }
</style>
