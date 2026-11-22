<script setup>
import { onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import dayjs from 'dayjs'
import api from '../api'

const { t } = useI18n()
const rows = ref([])
const users = ref({})
const entity = ref('')

async function load() {
  rows.value = (await api.get('/audit', { params: { entity: entity.value || undefined, limit: 300 } })).data
}
onMounted(async () => {
  users.value = Object.fromEntries((await api.get('/users')).data.map((u) => [u.id, u.full_name]))
  load()
})
</script>

<template>
  <div class="page">
    <div class="toolbar">
      <h1 class="page-title" style="margin: 0; flex: 1">{{ t('nav.audit') }}</h1>
      <el-select v-model="entity" clearable :placeholder="t('audit.entity')" style="width: 160px" @change="load">
        <el-option v-for="e in ['task', 'user', 'worker', 'shift_config', 'team', 'holiday', 'setting', 'glossary', 'system']" :key="e" :label="e" :value="e" />
      </el-select>
    </div>
    <el-table :data="rows" size="small" border>
      <el-table-column :label="t('audit.at')" width="150"><template #default="{ row }">{{ dayjs(row.at).format('YYYY-MM-DD HH:mm:ss') }}</template></el-table-column>
      <el-table-column :label="t('audit.user')" width="120"><template #default="{ row }">{{ users[row.user_id] ?? '—' }}</template></el-table-column>
      <el-table-column prop="action" :label="t('audit.action')" width="130" />
      <el-table-column :label="t('audit.entity')" width="140"><template #default="{ row }">{{ row.entity }} #{{ row.entity_id }}</template></el-table-column>
      <el-table-column prop="field" :label="t('audit.field')" width="120" />
      <el-table-column prop="old_value" :label="t('audit.old')" min-width="140" show-overflow-tooltip />
      <el-table-column prop="new_value" :label="t('audit.new')" min-width="140" show-overflow-tooltip />
    </el-table>
  </div>
</template>
