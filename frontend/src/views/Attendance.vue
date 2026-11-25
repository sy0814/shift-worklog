<script setup>
import { useRoute, useRouter } from 'vue-router'
import ScheduleGuide from '../components/ScheduleGuide.vue'
import WhyPanel from '../components/WhyPanel.vue'
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
import OvertimeDialog from '../components/OvertimeDialog.vue'
import { fullHours } from '../cycle'
import { fmtFull } from '../format'

const { t } = useI18n()
const auth = useAuth()
const route = useRoute()
const router = useRouter()
const month = ref(dayjs().format('YYYY-MM'))
const teamId = ref(auth.user?.team_id ?? auth.teams[0]?.id)
const data = ref(null)
const loading = ref(false)
const todayStr = dayjs().format('YYYY-MM-DD')

async function load() {
  loading.value = true
  try {
    const m = dayjs(month.value + '-01')
    const params = { team_id: teamId.value, start: m.format('YYYY-MM-DD'), end: m.endOf('month').format('YYYY-MM-DD') }
    const [a, op, ol] = await Promise.all([api.get('/attendance', { params }), api.get('/overtime/people', { params }),
      api.get('/overtime', { params })])
    data.value = a.data
    otPeople.value = op.data
    otList.value = ol.data
  } finally {
    loading.value = false
  }
}
watch([month, teamId], load)

// ---- 加班 ----
const otPeople = ref([]) // 展开到每个人的
const otList = ref([]) // 原始记录（整个班组的算一条）
const otCell = computed(() => {
  const m = {}
  for (const p of otPeople.value) m[`${p.worker_id}|${p.day}`] = (m[`${p.worker_id}|${p.day}`] || 0) + p.hours
  return m
})
const otSum = computed(() => {
  const m = {}
  for (const p of otPeople.value) m[p.worker_id] = Math.round(((m[p.worker_id] || 0) + p.hours) * 100) / 100
  return m
})
const otOpen = ref(false)
const otPreset = ref(null)
function openOvertime(preset) {
  otPreset.value = preset
  otOpen.value = true
}
async function delOvertime(o) {
  await ElMessageBox.confirm(t('ot.del'), t('ot.title'), { type: 'warning' })
  await api.delete(`/overtime/${o.id}`)
  load()
}
const fmtH = (h) => (Number.isInteger(h) ? h : h.toFixed(1))
// 从「为什么？」「怎么改排班？」的链接进来：?worker=员工 id&day=日期（打开这一格）；?team=班组 id&month=YYYY-MM
async function applyQuery(q) {
  if (q.team && auth.teams.some((x) => x.id === Number(q.team))) teamId.value = Number(q.team)
  if (q.month) month.value = q.month
  if (q.worker && q.day) {
    await ensureWorkers()
    const w0 = allWorkers.value.find((x) => x.id === Number(q.worker))
    month.value = q.day.slice(0, 7)
    if (w0?.team_id && auth.teams.some((x) => x.id === w0.team_id)) teamId.value = w0.team_id
  }
  await load()
  if (q.worker && q.day) {
    const w = data.value?.workers.find((x) => x.id === Number(q.worker))
    if (w && data.value.cells[w.id]?.[q.day]) openCell(w, q.day)
  }
  if (q.worker || q.team || q.month) router.replace({ query: {} }) // 刷新页面时不再自动弹出
}
onMounted(() => applyQuery(route.query))
watch(() => route.query, (q) => { if (q.worker || q.team || q.month) applyQuery(q) })

function code(c) {
  if (!c || c.status == null) return ''
  return c.status === 'present' ? t(`att.code.${c.shift_kind}`) : t(`att.code.${c.status}`)
}
const canEdit = (w) => auth.teamOk('attendance.edit', w.team_id)
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
const form = reactive({ status: 'present', shift_kind: null, team_id: null, note: '', until: null })
const allWorkers = ref([])
const swapWith = ref(null)
async function ensureWorkers() {
  if (!allWorkers.value.length) allWorkers.value = (await api.get('/workers')).data
}
const isGuest = (w) => data.value?.guest_ids?.includes(w.id)
const whyOpen = ref(false) // 「为什么？」展开（每次打开格子都收起，重新读）
async function openCell(w, day) {
  Object.assign(cur, { worker: w, day, cell: data.value.cells[w.id][day], tasks: [], loading: true })
  Object.assign(form, { status: cur.cell.status || 'present', shift_kind: cur.cell.shift_kind,
    team_id: cur.cell.team_id !== w.team_id ? cur.cell.team_id : null, note: cur.cell.note || '', until: null })
  swapWith.value = null
  whyOpen.value = false
  dlg.value = true
  ensureWorkers()
  try {
    cur.tasks = (await api.get(`/workers/${w.id}/day`, { params: { day } })).data.tasks
  } finally {
    cur.loading = false
  }
}
async function save(status) {
  const st = status || form.status
  const common = { status: st, note: form.note,
    shift_kind: st === 'present' ? form.shift_kind : null, team_id: st === 'present' ? form.team_id : null }
  if (form.until && form.until > cur.day) {
    // 连续多天：走批量接口
    await api.put('/attendance/batch', { worker_ids: [cur.worker.id], start: cur.day, end: form.until, ...common })
  } else {
    await api.put('/attendance', { worker_id: cur.worker.id, day: cur.day, ...common })
  }
  dlg.value = false
  ElMessage.success(t('common.saved'))
  load()
}

async function doSwap() {
  await api.post('/attendance/swap', { day: cur.day, worker_a: cur.worker.id, worker_b: swapWith.value, note: form.note })
  dlg.value = false
  ElMessage.success(t('att.swapped'))
  load()
}

// ---- 批量安排（例如周末临时几个人去顶某个班组）----
const batchOpen = ref(false)
const batch = reactive({ worker_ids: [], range: null, status: 'present', shift_kind: null, team_id: null, note: '' })
async function openBatch() {
  await ensureWorkers()
  Object.assign(batch, { worker_ids: [], range: null, status: 'present', shift_kind: null, team_id: teamId.value, note: '' })
  batchOpen.value = true
}
async function saveBatch() {
  const { data: r } = await api.put('/attendance/batch', {
    worker_ids: batch.worker_ids, start: batch.range[0], end: batch.range[1], status: batch.status, note: batch.note,
    shift_kind: batch.status === 'present' ? batch.shift_kind : null, team_id: batch.status === 'present' ? batch.team_id : null,
  })
  batchOpen.value = false
  ElMessage.success(t('att.batchDone', { n: r.updated }))
  load()
}
const workerGroups = computed(() => {
  const g = new Map()
  for (const w of allWorkers.value) {
    if (!g.has(w.team_id)) g.set(w.team_id, [])
    g.get(w.team_id).push(w)
  }
  return [...g.entries()].map(([tid, list]) => ({ label: tid ? localName(auth.teamById(tid)) : t('workers.noTeam'), list }))
})

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
      <el-button v-if="auth.can('attendance.edit')" @click="openBatch">{{ t('att.batch') }}</el-button>
      <el-button v-if="auth.can('overtime.edit')" @click="openOvertime({ mode: 'team', team_id: teamId })">{{ t('ot.add') }}</el-button>
      <el-button v-if="auth.can('export')" @click="exportOpen = true">{{ t('exp.title') }}</el-button>
      <template v-if="auth.isAdmin">
        <el-button @click="download('/attendance/template', {}, 'attendance_template.xlsx')">{{ t('att.template') }}</el-button>
        <el-button type="primary" @click="fileInput.click()">{{ t('att.import') }}</el-button>
        <input ref="fileInput" type="file" accept=".xlsx" hidden @change="importFile" />
      </template>
    </div>
    <div class="muted small">{{ t('att.defaultHint') }} · {{ t('att.legend') }}</div>

    <ScheduleGuide />
    <div v-loading="loading" :class="['grid-wrap', { first: !data }]">
      <table v-if="data" class="grid">
        <thead>
          <tr>
            <th class="name">{{ t('workers.name') }}</th>
            <th v-for="d in data.days" :key="d" :class="{ today: d === todayStr }">{{ d.slice(8) }}</th>
            <th>Σ</th>
            <th class="otc">{{ t('ot.sum') }}</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="w in data.workers" :key="w.id" :class="{ guest: isGuest(w) }">
            <td class="name">{{ w.name }}<el-tag v-if="isGuest(w)" size="small" type="warning" class="gtag">{{ t('att.guest') }} · {{ localName(auth.teamById(w.team_id)) }}</el-tag></td>
            <td v-for="d in data.days" :key="d"
                :class="['c', `s-${data.cells[w.id][d].status}`, { ex: data.cells[w.id][d].source !== 'default', today: d === todayStr }]"
                :title="data.cells[w.id][d].hours ? fullHours(data.cells[w.id][d].hours) : ''"
                @click="openCell(w, d)">{{ code(data.cells[w.id][d]) }}<i v-if="data.cells[w.id][d].hours" class="hmark">⏱</i><sup v-if="otCell[`${w.id}|${d}`]" class="ot">+{{ fmtH(otCell[`${w.id}|${d}`]) }}</sup></td>
            <td class="sum">{{ counts[w.id] }}</td>
            <td class="sum otc">{{ otSum[w.id] ? fmtH(otSum[w.id]) : '' }}</td>
          </tr>
        </tbody>
      </table>
      <el-empty v-if="data && !data.workers.length" />
    </div>

    <!-- 出勤表加载出来之前先不显示下面的加班记录，免得表格出来时把它往下推（页面跳动） -->
    <template v-if="data">
    <h4>{{ t('ot.list') }}</h4>
    <el-table v-if="otList.length" :data="otList" size="small" class="otlist">
      <el-table-column prop="day" :label="t('ot.day')" width="110" />
      <el-table-column :label="t('ot.target')" min-width="160">
        <template #default="{ row }">
          <template v-if="row.team_id">{{ localName(auth.teamById(row.team_id)) }} · {{ t('ot.wholeTeam', { n: row.people }) }}</template>
          <template v-else>{{ row.worker_name }}</template>
        </template>
      </el-table-column>
      <el-table-column :label="t('ot.until')" min-width="170">
        <template #default="{ row }">{{ t('shift.' + row.shift_kind) }} → {{ fmtFull(row.until) }} <span class="muted">({{ t('ot.hours', { n: fmtH(row.hours) }) }})</span></template>
      </el-table-column>
      <el-table-column prop="note" :label="t('ot.note')" min-width="120" />
      <el-table-column prop="created_by_name" :label="t('task.publisher')" width="110" />
      <el-table-column width="80">
        <template #default="{ row }"><el-button v-if="row.team_id ? auth.teamOk('overtime.edit', row.team_id) : auth.can('overtime.edit')" link type="danger" @click="delOvertime(row)">{{ t('common.delete') }}</el-button></template>
      </el-table-column>
    </el-table>
    <div v-else class="muted small">{{ t('ot.none') }}</div>
    </template>
    <OvertimeDialog v-model="otOpen" :preset="otPreset" @saved="load" />

    <el-dialog v-model="dlg" :title="cur.worker ? `${cur.worker.name} · ${cur.day}` : ''" width="min(560px, 96vw)" :fullscreen="isNarrow()" append-to-body>
      <template v-if="cur.worker">
        <div class="why-row">
          <span v-if="cur.cell.source !== 'default'" class="muted small">
            {{ cur.cell.source === 'import' ? t('att.importedSrc') : t('att.edited') }}
          </span>
          <el-button v-if="auth.whyOk(cur.worker.team_id)" link type="primary" size="small" style="margin-left: auto" @click="whyOpen = !whyOpen">{{ t('why.button') }} {{ whyOpen ? '▴' : '▾' }}</el-button>
        </div>
        <div v-if="whyOpen" class="why-box"><WhyPanel type="worker" :id="cur.worker.id" :day="cur.day" :hide="['attendance', 'overtime']" @navigate="dlg = false" /></div>
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
          <el-form-item :label="t('att.until')">
            <el-date-picker v-model="form.until" value-format="YYYY-MM-DD" :disabled-date="(d) => dayjs(d).format('YYYY-MM-DD') <= cur.day || dayjs(d).diff(cur.day, 'day') > 30" clearable style="width: 160px" />
          </el-form-item>
        </el-form>
        <div v-if="canEdit(cur.worker)" class="btns">
          <el-button v-if="cur.cell.status === 'present'" @click="dlg = false; openOvertime({ mode: 'people', day: cur.day, worker_ids: [cur.worker.id], team_id: cur.worker.team_id })">{{ t('ot.add') }}</el-button>
          <el-button v-if="cur.cell.source !== 'default'" @click="save('default')">{{ t('att.reset') }}</el-button>
          <el-button type="primary" @click="save()">{{ t('common.save') }}</el-button>
        </div>

        <template v-if="canEdit(cur.worker)">
          <h4>{{ t('att.swapWith') }}</h4>
          <div class="btns left">
            <el-select v-model="swapWith" filterable clearable :placeholder="t('att.swapPick')" style="width: 220px">
              <el-option-group v-for="g in workerGroups" :key="g.label" :label="g.label">
                <el-option v-for="x in g.list.filter((x) => x.id !== cur.worker.id)" :key="x.id" :label="x.name" :value="x.id" />
              </el-option-group>
            </el-select>
            <el-button type="warning" :disabled="!swapWith" @click="doSwap">{{ t('att.swap') }}</el-button>
          </div>
        </template>

        <h4>{{ t('att.dayTasks') }}</h4>
        <div v-loading="cur.loading" class="tasks">
          <TaskCard v-for="task in cur.tasks" :key="task.id" :task="task" @click="detailId = task.id; detailOpen = true" />
          <div v-if="!cur.loading && !cur.tasks.length" class="muted">{{ t('att.noTasks') }}</div>
        </div>
      </template>
    </el-dialog>

    <el-dialog v-model="batchOpen" :title="t('att.batch')" width="min(520px, 96vw)" :fullscreen="isNarrow()" append-to-body>
      <el-form label-width="auto">
        <el-form-item :label="t('att.workers')">
          <el-select v-model="batch.worker_ids" multiple filterable style="width: 100%">
            <el-option-group v-for="g in workerGroups" :key="g.label" :label="g.label">
              <el-option v-for="x in g.list" :key="x.id" :label="x.name" :value="x.id" />
            </el-option-group>
          </el-select>
        </el-form-item>
        <el-form-item :label="t('att.range')">
          <el-date-picker v-model="batch.range" type="daterange" value-format="YYYY-MM-DD" unlink-panels style="width: 100%" />
        </el-form-item>
        <el-form-item :label="t('att.status')">
          <el-radio-group v-model="batch.status">
            <el-radio-button v-for="s in ['present', 'leave', 'sick', 'absent', 'off']" :key="s" :value="s">{{ t(`att.st.${s}`) }}</el-radio-button>
          </el-radio-group>
        </el-form-item>
        <template v-if="batch.status === 'present'">
          <el-form-item :label="t('att.shiftActual')">
            <el-radio-group v-model="batch.shift_kind">
              <el-radio-button v-for="k in ['day', 'middle', 'night']" :key="k" :value="k">{{ t(`shift.${k}`) }}</el-radio-button>
            </el-radio-group>
            <el-button v-if="batch.shift_kind" link size="small" @click="batch.shift_kind = null">✕</el-button>
            <div class="muted small" style="width: 100%">{{ t('att.shiftAuto') }}</div>
          </el-form-item>
          <el-form-item :label="t('att.teamActual')">
            <el-select v-model="batch.team_id" clearable style="width: 160px">
              <el-option v-for="tm in auth.teams" :key="tm.id" :label="localName(tm)" :value="tm.id" />
            </el-select>
          </el-form-item>
        </template>
        <el-form-item :label="t('att.note')"><el-input v-model="batch.note" maxlength="200" /></el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="batchOpen = false">{{ t('common.cancel') }}</el-button>
        <el-button type="primary" :disabled="!batch.worker_ids.length || !batch.range" @click="saveBatch">{{ t('common.save') }}</el-button>
      </template>
    </el-dialog>

    <TaskDetail v-model="detailOpen" :task-id="detailId" />
    <ExportDialog v-model="exportOpen" :team-id="teamId" />
  </div>
</template>

<style scoped>
.why-row { display: flex; align-items: center; justify-content: space-between; gap: 8px; min-height: 24px; }
.why-box { margin: 4px 0 12px; padding: 8px 12px; border-radius: 6px; background: var(--el-fill-color-light); }
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
.ot { color: #e6a23c; font-size: 10px; font-weight: 600; margin-left: 1px; }
.otc { color: #b88230; min-width: 40px !important; }
.otlist { max-width: 900px; }
.btns { display: flex; justify-content: flex-end; gap: 8px; }
.btns.left { justify-content: flex-start; }
.gtag { margin-left: 6px; }
tr.guest .name { background: #fdf6ec; }
h4 { margin: 16px 0 8px; }
.tasks { display: flex; flex-direction: column; gap: 8px; min-height: 40px; }
.hmark { font-style: normal; font-size: 9px; vertical-align: super; opacity: .7; }
.grid-wrap.first { min-height: 240px; }
</style>
