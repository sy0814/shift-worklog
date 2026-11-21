<script setup>
import { onMounted, reactive, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { ElMessage, ElMessageBox } from 'element-plus'
import dayjs from 'dayjs'
import api from '../api'
import { LANGS, localName } from '../i18n'
import { useAuth } from '../stores/auth'

const { t } = useI18n()
const auth = useAuth()
const users = ref([])
const dialog = ref(false)
const editing = ref(null) // null = 新建
const form = reactive({})

async function load() {
  users.value = (await api.get('/users')).data
}
onMounted(load)

function openCreate() {
  editing.value = null
  Object.assign(form, { username: '', password: '', full_name: '', role: 'leader', team_id: null, lang: 'zh', is_active: true })
  dialog.value = true
}
function openEdit(u) {
  editing.value = u
  Object.assign(form, { full_name: u.full_name, role: u.role, team_id: u.team_id, lang: u.lang, is_active: u.is_active })
  dialog.value = true
}
async function save() {
  if (editing.value) {
    const { full_name, role, team_id, lang, is_active } = form
    await api.patch(`/users/${editing.value.id}`, { full_name, role, team_id, lang, is_active })
  } else {
    const { username, password, full_name, role, team_id, lang } = form
    await api.post('/users', { username, password, full_name, role, team_id, lang })
  }
  dialog.value = false
  ElMessage.success(t('common.saved'))
  load()
}
async function resetPassword(u) {
  const { value } = await ElMessageBox.prompt(t('users.newPassword'), `${t('users.resetPassword')} · ${u.username}`, {
    inputType: 'password', inputPattern: /^.{6,}$/, inputErrorMessage: '≥ 6',
  })
  await api.post(`/users/${u.id}/reset-password`, { password: value })
  ElMessage.success(t('common.saved'))
}
</script>

<template>
  <div class="page">
    <div class="toolbar">
      <h1 class="page-title" style="margin: 0; flex: 1">{{ t('nav.users') }}</h1>
      <el-button type="primary" @click="openCreate">{{ t('common.add') }}</el-button>
    </div>
    <el-table :data="users" size="small" border>
      <el-table-column prop="username" :label="t('users.username')" min-width="120" />
      <el-table-column prop="full_name" :label="t('users.fullName')" min-width="120" />
      <el-table-column :label="t('users.role')" width="110"><template #default="{ row }">{{ t(`users.${row.role}`) }}</template></el-table-column>
      <el-table-column :label="t('users.team')" width="120"><template #default="{ row }">{{ localName(auth.teamById(row.team_id)) }}</template></el-table-column>
      <el-table-column :label="t('users.lang')" width="90"><template #default="{ row }">{{ LANGS.find((l) => l.code === row.lang)?.label }}</template></el-table-column>
      <el-table-column :label="t('users.active')" width="80" align="center">
        <template #default="{ row }"><el-tag :type="row.is_active ? 'success' : 'info'" size="small">{{ row.is_active ? t('common.yes') : t('common.no') }}</el-tag></template>
      </el-table-column>
      <el-table-column :label="t('users.created')" width="140"><template #default="{ row }">{{ dayjs(row.created_at).format('YYYY-MM-DD HH:mm') }}</template></el-table-column>
      <el-table-column :label="t('common.actions')" width="180" fixed="right">
        <template #default="{ row }">
          <el-button link type="primary" @click="openEdit(row)">{{ t('common.edit') }}</el-button>
          <el-button link type="warning" @click="resetPassword(row)">{{ t('users.resetPassword') }}</el-button>
        </template>
      </el-table-column>
    </el-table>

    <el-dialog v-model="dialog" :title="editing ? `${t('common.edit')} · ${editing.username}` : t('common.add')" width="min(460px, 92vw)">
      <el-form label-width="auto">
        <template v-if="!editing">
          <el-form-item :label="t('users.username')"><el-input v-model="form.username" /></el-form-item>
          <el-form-item :label="t('users.password')"><el-input v-model="form.password" type="password" show-password /></el-form-item>
        </template>
        <el-form-item :label="t('users.fullName')"><el-input v-model="form.full_name" /></el-form-item>
        <el-form-item :label="t('users.role')">
          <el-radio-group v-model="form.role">
            <el-radio value="leader">{{ t('users.leader') }}</el-radio>
            <el-radio value="admin">{{ t('users.admin') }}</el-radio>
          </el-radio-group>
        </el-form-item>
        <el-form-item v-if="form.role === 'leader'" :label="t('users.team')">
          <el-select v-model="form.team_id">
            <el-option v-for="team in auth.teams" :key="team.id" :label="localName(team)" :value="team.id" />
          </el-select>
        </el-form-item>
        <el-form-item :label="t('users.lang')">
          <el-select v-model="form.lang"><el-option v-for="l in LANGS" :key="l.code" :label="l.label" :value="l.code" /></el-select>
        </el-form-item>
        <el-form-item v-if="editing" :label="t('users.active')"><el-switch v-model="form.is_active" /></el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialog = false">{{ t('common.cancel') }}</el-button>
        <el-button type="primary" @click="save">{{ t('common.save') }}</el-button>
      </template>
    </el-dialog>
  </div>
</template>
