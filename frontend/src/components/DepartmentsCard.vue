<script setup>
// 系统设置 → 车间管理（系统管理员）：新增 / 改名 / 停用 / 删除车间。
// 新车间的班组在「排班 → 班组管理」里加（先在顶栏切换到那个车间）。
import RowActions from './RowActions.vue'
import { useActionsWidth } from '../rowActions'
import { reactive, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { ElMessage, ElMessageBox } from 'element-plus'
import api from '../api'
import { localName } from '../i18n'
import { useAuth } from '../stores/auth'
import TriNames from './TriNames.vue'

const { t } = useI18n()
const actW = useActionsWidth(() => [t('common.edit'), t('common.delete')])
const auth = useAuth()

const open = ref(false)
const editing = ref(null)
const form = reactive({ name_zh: '', name_sr: '', name_en: '', is_active: true })
const teamsOf = (id) => auth.allTeams.filter((x) => x.department_id === id).length

function edit(d) {
  editing.value = d
  Object.assign(form, d ? { name_zh: d.name_zh, name_sr: d.name_sr, name_en: d.name_en, is_active: d.is_active }
    : { name_zh: '', name_sr: '', name_en: '', is_active: true })
  open.value = true
}
async function save() {
  if (editing.value) await api.put(`/departments/${editing.value.id}`, form)
  else await api.post('/departments', form)
  open.value = false
  await auth.loadTeams()
  ElMessage.success(t('common.saved'))
}
async function remove(d) {
  await ElMessageBox.confirm(t('dept.delConfirm', { n: localName(d) }), t('common.delete'), { type: 'warning' })
  await api.delete(`/departments/${d.id}`)
  await auth.loadTeams()
}
</script>

<template>
  <el-card shadow="never" class="mb">
    <template #header>
      <div class="hd"><b>{{ t('dept.manage') }}</b><el-button size="small" type="primary" @click="edit(null)">{{ t('dept.add') }}</el-button></div>
    </template>
    <p class="muted small">{{ t('dept.hint') }}</p>
    <el-table :data="auth.departments" size="small" border>
      <el-table-column :label="t('dept.name')" min-width="200">
        <template #default="{ row }">
          <b>{{ localName(row) }}</b>
          <el-tag v-if="!row.is_active" size="small" type="info" class="ml">{{ t('dept.inactive') }}</el-tag>
          <div class="muted small">{{ [row.name_zh, row.name_sr, row.name_en].filter((x) => x !== localName(row)).join(' / ') }}</div>
        </template>
      </el-table-column>
      <el-table-column :label="t('workers.team')" width="110" align="center">
        <template #default="{ row }">{{ teamsOf(row.id) }}</template>
      </el-table-column>
      <el-table-column :label="t('common.actions')" :width="actW" fixed="right">
        <template #default="{ row }">
          <RowActions :items="[{ label: t('common.edit'), type: 'primary', onClick: () => edit(row) },
                               ...(auth.departments.length > 1 ? [{ label: t('common.delete'), type: 'danger', onClick: () => remove(row) }] : [])]" />
        </template>
      </el-table-column>
    </el-table>

    <el-dialog v-model="open" :title="editing ? t('common.edit') : t('dept.add')" width="min(520px, 94vw)" append-to-body>
      <el-form label-position="top">
        <el-form-item :label="t('dept.name')"><TriNames v-model="form" :maxlength="100" /></el-form-item>
        <el-form-item><el-checkbox v-model="form.is_active">{{ t('dept.active') }}</el-checkbox></el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="open = false">{{ t('common.cancel') }}</el-button>
        <el-button type="primary" :disabled="!(form.name_zh || form.name_sr || form.name_en)?.trim()" @click="save">{{ t('common.save') }}</el-button>
      </template>
    </el-dialog>
  </el-card>
</template>

<style scoped>
.hd { display: flex; justify-content: space-between; align-items: center; }
.muted { color: #909399; }
.small { font-size: 12px; }
.ml { margin-left: 6px; }
.mb { margin-bottom: 16px; }
</style>
