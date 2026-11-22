<script setup>
// 导出 Excel：时间段 + 班组 + 人员 + 表格语言
import { computed, reactive, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import dayjs from 'dayjs'
import api, { download } from '../api'
import { LANGS, localName } from '../i18n'
import { useAuth } from '../stores/auth'

const props = defineProps({ teamId: { type: Number, default: null } })
const visible = defineModel({ type: Boolean })
const { t, locale } = useI18n()
const auth = useAuth()
const workers = ref([])
const busy = ref(false)
const form = reactive({ range: null, team_id: null, worker_id: null, lang: 'zh' })

watch(visible, async (v) => {
  if (!v) return
  form.range = [dayjs().startOf('month').format('YYYY-MM-DD'), dayjs().format('YYYY-MM-DD')]
  form.team_id = auth.isAdmin ? props.teamId : auth.user.team_id
  form.worker_id = null
  form.lang = locale.value
  workers.value = (await api.get('/workers')).data
})
const teamWorkers = computed(() => workers.value.filter((w) => !form.team_id || w.team_id === form.team_id))

async function submit() {
  busy.value = true
  try {
    await download('/export/tasks', {
      start: form.range[0], end: form.range[1], lang: form.lang,
      team_id: form.team_id || undefined, worker_id: form.worker_id || undefined,
    }, 'worklog.xlsx')
    visible.value = false
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <el-dialog v-model="visible" :title="t('exp.title')" width="min(460px, 94vw)" append-to-body>
    <el-form label-position="top">
      <el-form-item :label="t('exp.range')">
        <el-date-picker v-model="form.range" type="daterange" value-format="YYYY-MM-DD" unlink-panels :clearable="false" style="width: 100%" />
      </el-form-item>
      <el-form-item :label="t('exp.team')">
        <el-select v-model="form.team_id" :disabled="!auth.isAdmin" clearable :placeholder="t('exp.all')" @change="form.worker_id = null">
          <el-option v-for="tm in auth.teams" :key="tm.id" :label="localName(tm)" :value="tm.id" />
        </el-select>
      </el-form-item>
      <el-form-item :label="t('exp.worker')">
        <el-select v-model="form.worker_id" clearable filterable :placeholder="t('exp.all')">
          <el-option v-for="w in teamWorkers" :key="w.id" :label="w.name" :value="w.id" />
        </el-select>
      </el-form-item>
      <el-form-item :label="t('exp.lang')">
        <el-radio-group v-model="form.lang">
          <el-radio-button v-for="l in LANGS" :key="l.code" :value="l.code">{{ l.label }}</el-radio-button>
        </el-radio-group>
      </el-form-item>
      <div class="muted">{{ t('exp.note') }}</div>
    </el-form>
    <template #footer>
      <el-button @click="visible = false">{{ t('common.cancel') }}</el-button>
      <el-button type="primary" :loading="busy" :disabled="!form.range" @click="submit">{{ t('exp.download') }}</el-button>
    </template>
  </el-dialog>
</template>

<style scoped>
.muted { color: #909399; font-size: 13px; }
</style>
