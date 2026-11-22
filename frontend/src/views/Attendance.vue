<script setup>
// 出勤表：按月、按班组；点格子看此人当天做了什么，并可修改出勤
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { ElMessage, ElMessageBox } from 'element-plus'
import dayjs from 'dayjs'
import api, { download } from '../api'
import { localName } from '../i18n'
import { isNarrow } from '../format'
import { useAuth } from '../stores/auth'
import TaskCard from '../components/TaskCard.vue'
import TaskDetail from '../components/TaskDetail.vue'
import ExportDialog from '../components/ExportDialog.vue'

const { t } = useI18n()
const auth = useAuth()
const month = ref(dayjs().format('YYYY-MM'))
const teamId = ref(auth.user?.team_id ?? auth.teams[0]?.id)
const data = ref(null)
const loading = ref(false)
const todayStr = dayjs().format('YYYY-MM-DD')

async function load() {
  loading.value = true
  try {
    const m = dayjs(month.value + '-01')
    data.value = (await api.get('/attendance', { params: {
      team_id: teamId.value, start: m.format('YYYY-MM-DD'), end: m.endOf('month').format('YYYY-MM-DD'),
    } })).data
  } finally {
    loading.value = false
  }
}
watch([month, teamId], load)
onMounted(load)

function code(c) {
  if (!c || c.status == null) return ''
  return c.status === 'present' ? t(`att.code.${c.shift_kind}`) : t(`att.code.${c.status}`)
}
const canEdit = (w) => auth.isAdmin || w.team_id === auth.user?.team_id
const counts = computed(() => {
  if (!data.value) return {}
  const out = {}
  for (const w of data.value.workers) {
    const cells = Object.values(data.value.cells[w.id] || {})
    out[w.id] = cells.filter((c) => c.status === 'present').length
  }
  return out
})

// ---- 点格子：当天任务 + 修改出勤 ----
const dlg = ref(false)
const cur = reactive({ worker: null, day: null, cell: null, tasks: [], loading: false })
const form = reactive({ status: 'present', shift_kind: null, team_id: null, note: '' })
async function openCell(w, day) {
  Object.assign(cur, { worker: w, day, cell: data.value.cells[w.id][day], tasks: [], loading: true })
  Object.assign(form, { status: cur.cell.status || 'present', shift_kind: cur.cell.shift_kind, team_id: null, note: cur.cell.note || '' })
  dlg.value = true
  try {
    cur.tasks = (await api.get(`/workers/${w.id}/day`, { params: { day } })).data.tasks
  } finally {
    cur.loading = false
  }
}
async function save(status) {
  const body = { worker_id: cur.worker.id, day: cur.day, status: status || form.status, note: form.note,
    shift_kind: form.status === 'present' ? form.shift_kind : null, team_id: form.status === 'present' ? form.team_id : null }
  await api.put('/attendance', body)
  dlg.value = false
  ElMessage.success(t('common.saved'))
  load()
}

// ---- 导入 ----
const fileInput = ref()
async function importFile(e) {
  const f = e.target.files[0]
  e.target.value = ''
  if (!f) return
  const fd = new FormData()
  fd.append('file', f)
  const { data: r } = await api.post('/attendance/import', fd, { timeout: 120000 })
  if (r.errors.length) {
    const lines = r.errors.slice(0, 30).map((x) => `${x.row ? t('att.row', { n: x.row }) + '：' : ''}${x.message}`).join('<br>')
    ElMessageBox.alert(`<p>${t('att.importFailed', { n: r.errors.length })}</p><div style="max-height:50vh;overflow:auto;font-size:13px">${lines}</div>`,
      t('att.import'), { dangerouslyUseHTMLString: true, type: 'error' })
  } else {
    ElMessage.success(t('att.imported', { n: r.imported }))
    load()
  }
}

const detailOpen = ref(false)
const detailId = ref(null)
const exportOpen = ref(false)
</script>

<template>
  <div class="page">
    <div class="toolbar">
      <el-date-picker v-model="month" type="month" value-format="YYYY-MM" :clearable="false" style="width: 130px" />
      <el-radio-group v-model="teamId">
        <el-radio-button v-for="tm in auth.teams" :key="tm.id" :value="tm.id">{{ localName(tm) }}</el-radio-button>
      </el-radio-group>
      <span class="spacer" />
      <el-button @click="exportOpen = true">{{ t('exp.title') }}</el-button>
      <template v-if="auth.isAdmin">
        <el-button @click="download('/attendance/template', {}, 'attendance_template.xlsx')">{{ t('att.template') }}</el-button>
        <el-button type="primary" @click="fileInput.click()">{{ t('att.import') }}</el-button>
        <input ref="fileInput" type="file" accept=".xlsx" hidden @change="importFile" />
      </template>
    </div>
    <div class="muted small">{{ t('att.defaultHint') }} · {{ t('att.legend') }}</div>

    <div v-loading="loading" class="grid-wrap">
      <table v-if="data" class="grid">
        <thead>
          <tr>
            <th class="name">{{ t('workers.name') }}</th>
            <th v-for="d in data.days" :key="d" :class="{ today: d === todayStr }">{{ d.slice(8) }}</th>
            <th>Σ</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="w in data.workers" :key="w.id">
            <td class="name">{{ w.name }}</td>
            <td v-for="d in data.days" :key="d"
                :class="['c', `s-${data.cells[w.id][d].status}`, { ex: data.cells[w.id][d].source !== 'default', today: d === todayStr }]"
                @click="openCell(w, d)">{{ code(data.cells[w.id][d]) }}</td>
            <td class="sum">{{ counts[w.id] }}</td>
          </tr>
        </tbody>
      </table>
      <el-empty v-if="data && !data.workers.length" />
    </div>

    <el-dialog v-model="dlg" :title="cur.worker ? `${cur.worker.name} · ${cur.day}` : ''" width="min(560px, 96vw)" :fullscreen="isNarrow()" append-to-body>
      <template v-if="cur.worker">
        <div v-if="cur.cell.source !== 'default'" class="muted small">
          {{ cur.cell.source === 'import' ? t('att.importedSrc') : t('att.edited') }}
        </div>
        <el-form label-width="auto" :disabled="!canEdit(cur.worker)">
          <el-form-item :label="t('att.status')">
            <el-radio-group v-model="form.status">
              <el-radio-button v-for="s in ['present', 'leave', 'sick', 'absent', 'off']" :key="s" :value="s">{{ t(`att.st.${s}`) }}</el-radio-button>
            </el-radio-group>
          </el-form-item>
          <template v-if="form.status === 'present'">
            <el-form-item :label="t('att.shiftActual')">
              <el-radio-group v-model="form.shift_kind">
                <el-radio-button v-for="k in ['day', 'middle', 'night']" :key="k" :value="k">{{ t(`shift.${k}`) }}</el-radio-button>
              </el-radio-group>
            </el-form-item>
            <el-form-item :label="t('att.teamActual')">
              <el-select v-model="form.team_id" clearable :placeholder="localName(auth.teamById(cur.worker.team_id))" style="width: 160px">
                <el-option v-for="tm in auth.teams" :key="tm.id" :label="localName(tm)" :value="tm.id" />
              </el-select>
            </el-form-item>
          </template>
          <el-form-item :label="t('att.note')"><el-input v-model="form.note" maxlength="200" /></el-form-item>
        </el-form>
        <div v-if="canEdit(cur.worker)" class="btns">
          <el-button v-if="cur.cell.source !== 'default'" @click="save('default')">{{ t('att.reset') }}</el-button>
          <el-button type="primary" @click="save()">{{ t('common.save') }}</el-button>
        </div>

        <h4>{{ t('att.dayTasks') }}</h4>
        <div v-loading="cur.loading" class="tasks">
          <TaskCard v-for="task in cur.tasks" :key="task.id" :task="task" @click="detailId = task.id; detailOpen = true" />
          <div v-if="!cur.loading && !cur.tasks.length" class="muted">{{ t('att.noTasks') }}</div>
        </div>
      </template>
    </el-dialog>

    <TaskDetail v-model="detailOpen" :task-id="detailId" />
    <ExportDialog v-model="exportOpen" :team-id="teamId" />
  </div>
</template>

<style scoped>
.spacer { flex: 1; }
.muted { color: #909399; }
.small { font-size: 12px; margin-bottom: 8px; }
.grid-wrap { overflow-x: auto; background: #fff; border-radius: 8px; min-height: 100px; }
.grid { border-collapse: collapse; font-size: 13px; width: max-content; min-width: 100%; }
.grid th, .grid td { border: 1px solid #ebeef5; padding: 4px 0; text-align: center; min-width: 26px; }
.grid th { background: #f5f7fa; font-weight: 500; position: sticky; top: 0; }
.grid .name { position: sticky; left: 0; background: #fff; text-align: left; padding: 4px 8px; min-width: 110px; z-index: 1; white-space: nowrap; }
.grid th.name { background: #f5f7fa; z-index: 2; }
.c { cursor: pointer; }
.c:hover { outline: 2px solid #409eff; outline-offset: -2px; }
.s-off { color: #c0c4cc; background: #fafafa; }
.s-leave { background: #fff2cc; }
.s-sick { background: #fce4d6; }
.s-absent { background: #f8cbad; color: #c45656; }
.ex { font-weight: 700; font-style: italic; }
.today { box-shadow: inset 0 0 0 2px #409eff; }
.sum { font-weight: 600; background: #f5f7fa; }
.btns { display: flex; justify-content: flex-end; gap: 8px; }
h4 { margin: 16px 0 8px; }
.tasks { display: flex; flex-direction: column; gap: 8px; min-height: 40px; }
</style>
