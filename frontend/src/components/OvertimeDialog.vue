<script setup>
// 设置加班：给几个人，或者整个班组，某个班次加班到几点
import { computed, reactive, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { ElMessage } from 'element-plus'
import dayjs from 'dayjs'
import api from '../api'
import { localName } from '../i18n'
import { useAuth } from '../stores/auth'

// preset：{ day, worker_ids, team_id, mode: 'people' | 'team', shift_kind }
const props = defineProps({ preset: { type: Object, default: null } })
const visible = defineModel({ type: Boolean })
const emit = defineEmits(['saved'])
const { t } = useI18n()
const auth = useAuth()
const workers = ref([])
const saving = ref(false)
const form = reactive({ mode: 'people', day: '', worker_ids: [], team_id: null, shift_kind: null, until: '18:00', note: '' })

watch(visible, async (v) => {
  if (!v) return
  const p = props.preset || {}
  Object.assign(form, {
    mode: p.mode || (p.worker_ids?.length ? 'people' : 'team'), day: p.day || dayjs().format('YYYY-MM-DD'),
    worker_ids: [...(p.worker_ids || [])], team_id: p.team_id ?? auth.user?.team_id ?? auth.teams[0]?.id,
    shift_kind: p.shift_kind || null, until: form.until, note: '',
  })
  if (!workers.value.length) workers.value = (await api.get('/workers')).data
})

// 班长只能选本班组（管理员任何班组）；人员按班组分组、本班组在前
const teams = computed(() => auth.teams.filter((x) => auth.teamOk('overtime.edit', x.id)))
const groups = computed(() => {
  const m = new Map()
  for (const w of workers.value) {
    if (!m.has(w.team_id)) m.set(w.team_id, [])
    m.get(w.team_id).push(w)
  }
  return [...m.entries()].sort(([a], [b]) => (a === form.team_id ? -1 : b === form.team_id ? 1 : (a ?? 99) - (b ?? 99)))
    .map(([tid, list]) => ({ label: tid ? localName(auth.teamById(tid)) : t('workers.noTeam'), list }))
})

async function save() {
  saving.value = true
  try {
    const body = { day: form.day, until: form.until, note: form.note, shift_kind: form.shift_kind || null,
      ...(form.mode === 'team' ? { team_id: form.team_id } : { worker_ids: form.worker_ids }) }
    await api.post('/overtime', body)
    ElMessage.success(t('ot.saved'))
    visible.value = false
    emit('saved')
  } finally {
    saving.value = false
  }
}
</script>

<template>
  <el-dialog v-model="visible" :title="t('ot.add')" width="min(520px, 96vw)" append-to-body>
    <el-form label-width="auto">
      <el-form-item :label="t('ot.target')">
        <el-radio-group v-model="form.mode">
          <el-radio-button value="people">{{ t('ot.people') }}</el-radio-button>
          <el-radio-button value="team">{{ t('ot.team') }}</el-radio-button>
        </el-radio-group>
      </el-form-item>
      <el-form-item v-if="form.mode === 'team'" :label="t('task.team')">
        <el-select v-model="form.team_id" style="width: 160px">
          <el-option v-for="tm in teams" :key="tm.id" :label="localName(tm)" :value="tm.id" />
        </el-select>
        <div class="muted">{{ t('ot.teamHint') }}</div>
      </el-form-item>
      <el-form-item v-else :label="t('att.workers')">
        <el-select v-model="form.worker_ids" multiple filterable style="width: 100%">
          <el-option-group v-for="g in groups" :key="g.label" :label="g.label">
            <el-option v-for="w in g.list" :key="w.id" :label="w.name" :value="w.id" />
          </el-option-group>
        </el-select>
      </el-form-item>
      <el-form-item :label="t('ot.day')">
        <el-date-picker v-model="form.day" value-format="YYYY-MM-DD" :clearable="false" style="width: 160px" />
      </el-form-item>
      <el-form-item :label="t('ot.shift')">
        <el-radio-group v-model="form.shift_kind">
          <el-radio-button v-for="k in ['day', 'middle', 'night']" :key="k" :value="k">{{ t('shift.' + k) }}</el-radio-button>
        </el-radio-group>
        <el-button v-if="form.shift_kind" link size="small" @click="form.shift_kind = null">✕</el-button>
        <div class="muted">{{ t('ot.shiftAuto') }}</div>
      </el-form-item>
      <el-form-item :label="t('ot.until')">
        <el-time-select v-model="form.until" start="00:00" step="00:15" end="23:45" :clearable="false" style="width: 130px" />
      </el-form-item>
      <el-form-item :label="t('ot.note')"><el-input v-model="form.note" maxlength="200" /></el-form-item>
    </el-form>
    <template #footer>
      <el-button @click="visible = false">{{ t('common.cancel') }}</el-button>
      <el-button type="primary" :loading="saving" :disabled="form.mode === 'people' ? !form.worker_ids.length : !form.team_id" @click="save">{{ t('common.save') }}</el-button>
    </template>
  </el-dialog>
</template>

<style scoped>
.muted { color: #909399; font-size: 12px; width: 100%; line-height: 1.5; }
</style>
