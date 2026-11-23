<script setup>
// 定期巡查：巡查项列表、编辑（带「接下来 5 次」实时预览）、立即派发、派发记录
// 管理员管理全部；班长只能管理「固定派给本班组」的巡查项，其他的只读
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { ElMessage, ElMessageBox } from 'element-plus'
import dayjs from 'dayjs'
import api from '../api'
import { localName } from '../i18n'
import { fmtFull, isNarrow } from '../format'
import { useAuth } from '../stores/auth'
import ShiftTag from '../components/ShiftTag.vue'
import TaskDetail from '../components/TaskDetail.vue'

const { t, tm, locale } = useI18n()
const auth = useAuth()
const rows = ref([])
const workers = ref([])

async function load() {
  rows.value = (await api.get('/inspections')).data
}
onMounted(async () => {
  await load()
  workers.value = (await api.get('/workers')).data
})

const hhmm = (v) => (v || '').slice(0, 5)
const teamName = (id) => localName(auth.teamById(id))
function summary(r) {
  const tt = hhmm(r.at_time)
  const k = (r.shift_kinds || []).map((x) => t(`shift.${x}`)).join('/')
  let s
  if (r.kind === 'daily') s = r.every_n > 1 ? t('insp.sum.dailyN', { n: r.every_n, t: tt }) : t('insp.sum.daily', { t: tt })
  else if (r.kind === 'weekly') s = t('insp.sum.weekly', { d: r.weekdays.map((d) => tm('insp.wd')[d]).join('、'), t: tt })
  else if (r.kind === 'monthly') s = t('insp.sum.monthly', { d: r.month_days.join('、'), t: tt })
  else if (r.kind === 'yearly') {
    const d = r.year_dates.map(ymd).join('、')
    s = r.every_n > 1 ? t('insp.sum.yearlyN', { n: r.every_n, d, t: tt }) : t('insp.sum.yearly', { d, t: tt })
  }
  else s = r.every_n > 1 ? t('insp.sum.shiftN', { n: r.every_n, k }) : t('insp.sum.shift', { k })
  if (r.kind === 'shift' && r.assign === 'fixed') s += t('insp.sum.own', { team: teamName(r.team_id) })
  return s
}
// "MM-DD" → 按界面语言显示：3月15日 / 15.3. / Mar 15
function ymd(v) {
  const [m, d] = v.split('-').map(Number)
  if (locale.value === 'zh') return `${m}月${d}日`
  if (locale.value === 'sr') return `${d}.${m}.`
  return dayjs(new Date(2024, m - 1, d)).format('MMM D')
}
const who = (r) => (r.assign === 'fixed' ? teamName(r.team_id) : t('insp.onDuty'))

async function toggle(r, v) {
  await api.put(`/inspections/${r.id}`, { ...payloadOf(r), enabled: v })
  ElMessage.success(t('common.saved'))
  load()
}

// ---------------- 编辑 ----------------
const dlg = ref(false)
const editing = ref(null)
const form = reactive({})
const blank = () => ({
  name: '', content: '', lang: locale.value, enabled: true, kind: 'daily', at_time: '08:00', every_n: 1,
  weekdays: [], month_days: [], year_dates: [], shift_kinds: [], start_date: dayjs().format('YYYY-MM-DD'),
  ...(auth.isAdmin ? { assign: 'on_duty', team_id: null } : { assign: 'fixed', team_id: auth.user.team_id }), worker_ids: [],
})
function payloadOf(r) {
  const p = {}
  for (const k of Object.keys(blank())) p[k] = r[k]
  p.at_time = hhmm(r.at_time)
  p.year_dates = [...(r.year_dates || [])]
  return p
}
function openEdit(r) {
  editing.value = r || null
  Object.assign(form, r ? payloadOf(r) : blank())
  preview.value = []
  dlg.value = true
}
// 每年：选月、日，加到列表里
const ym = ref(1)
const yd = ref(1)
const daysIn = (m) => new Date(2024, m, 0).getDate() // 2024 是闰年，2 月可选 29 日
watch(ym, (m) => { if (yd.value > daysIn(m)) yd.value = daysIn(m) })
function addYearDate() {
  const v = `${String(ym.value).padStart(2, '0')}-${String(yd.value).padStart(2, '0')}`
  if (!form.year_dates.includes(v)) form.year_dates = [...form.year_dates, v].sort()
}
const teamWorkers = computed(() => workers.value.filter((w) => w.team_id === form.team_id))
watch(() => form.team_id, (v, old) => { if (old !== undefined && v !== old) form.worker_ids = [] })

// 实时预览（防抖）
const preview = ref([])
const previewErr = ref('')
let pt = null
watch(form, () => {
  if (!dlg.value) return
  clearTimeout(pt)
  pt = setTimeout(async () => {
    try {
      preview.value = (await api.post('/inspections/preview', { ...form, name: form.name || 'x', content: form.content || 'x' }, { silent: true })).data
      previewErr.value = preview.value.length ? '' : t('insp.noRule')
    } catch {
      preview.value = []
      previewErr.value = t('insp.noRule')
    }
  }, 300)
}, { deep: true })

async function save() {
  if (editing.value) await api.put(`/inspections/${editing.value.id}`, { ...form })
  else await api.post('/inspections', { ...form })
  dlg.value = false
  ElMessage.success(t('common.saved'))
  load()
}
async function remove(r) {
  if (r.runs) return ElMessage.warning(t('insp.noDelete'))
  await ElMessageBox.confirm(t('insp.confirmDelete'), r.name, { type: 'warning' })
  await api.delete(`/inspections/${r.id}`)
  load()
}
async function runNow(r) {
  await api.post(`/inspections/${r.id}/run-now`)
  ElMessage.success(t('insp.dispatched'))
  load()
}

// ---------------- 派发记录 ----------------
const hist = ref(false)
const histOf = ref(null)
const runs = ref([])
async function openHistory(r) {
  histOf.value = r
  runs.value = (await api.get(`/inspections/${r.id}/runs`)).data
  hist.value = true
}
const detailOpen = ref(false)
const detailId = ref(null)
const runType = { created: 'success', manual: 'primary', skipped: 'info', failed: 'danger' }
</script>

<template>
  <div class="page">
    <div class="toolbar">
      <h1 class="page-title" style="margin: 0; flex: 1">{{ t('insp.title') }}</h1>
      <el-button v-if="auth.isAdmin || auth.user?.team_id" type="primary" @click="openEdit(null)">{{ t('insp.add') }}</el-button>
    </div>
    <div v-if="!auth.isAdmin" class="muted small hint">{{ t('insp.leaderHint') }}</div>

    <el-table :data="rows" size="small" border>
      <el-table-column :label="t('insp.enabled')" width="70" align="center">
        <template #default="{ row }"><el-switch :model-value="row.enabled" size="small" :disabled="!row.can_edit" @change="(v) => toggle(row, v)" /></template>
      </el-table-column>
      <el-table-column prop="name" :label="t('insp.name')" min-width="140" />
      <el-table-column :label="t('insp.kind')" min-width="200"><template #default="{ row }">{{ summary(row) }}</template></el-table-column>
      <el-table-column :label="t('insp.assign')" width="160"><template #default="{ row }">{{ who(row) }}</template></el-table-column>
      <el-table-column :label="t('insp.nextRun')" width="140"><template #default="{ row }">{{ row.next_run_at ? fmtFull(row.next_run_at) : '—' }}</template></el-table-column>
      <el-table-column :label="t('insp.lastRun')" width="140"><template #default="{ row }">{{ row.last_run_at ? fmtFull(row.last_run_at) : '—' }}</template></el-table-column>
      <el-table-column prop="runs" :label="t('insp.runs')" width="80" align="center" />
      <el-table-column :label="t('common.actions')" width="230" fixed="right">
        <template #default="{ row }">
          <template v-if="row.can_edit">
            <el-button link type="primary" @click="openEdit(row)">{{ t('common.edit') }}</el-button>
            <el-button link type="success" @click="runNow(row)">{{ t('insp.runNow') }}</el-button>
          </template>
          <el-button link @click="openHistory(row)">{{ t('insp.history') }}</el-button>
          <el-button v-if="row.can_edit" link type="danger" @click="remove(row)">{{ t('common.delete') }}</el-button>
        </template>
      </el-table-column>
    </el-table>

    <el-dialog v-model="dlg" :title="editing ? `${t('common.edit')} · ${editing.name}` : t('insp.add')" width="min(760px, 96vw)" :fullscreen="isNarrow()" append-to-body>
      <div class="edit">
        <el-form label-width="auto" class="f">
          <el-form-item :label="t('insp.name')"><el-input v-model="form.name" maxlength="100" /></el-form-item>
          <el-form-item :label="t('insp.content')">
            <el-input v-model="form.content" type="textarea" :autosize="{ minRows: 2, maxRows: 6 }" maxlength="2000" :placeholder="t('task.contentPh')" />
          </el-form-item>
          <el-form-item :label="t('insp.kind')">
            <el-radio-group v-model="form.kind">
              <el-radio-button v-for="k in ['daily', 'weekly', 'monthly', 'yearly', 'shift']" :key="k" :value="k">{{ t(`insp.kinds.${k}`) }}</el-radio-button>
            </el-radio-group>
          </el-form-item>

          <template v-if="form.kind === 'weekly'">
            <el-form-item :label="t('insp.weekdays')">
              <el-checkbox-group v-model="form.weekdays">
                <el-checkbox-button v-for="(d, i) in tm('insp.wd')" :key="i" :value="i">{{ d }}</el-checkbox-button>
              </el-checkbox-group>
            </el-form-item>
          </template>
          <template v-if="form.kind === 'monthly'">
            <el-form-item :label="t('insp.monthDays')">
              <el-select v-model="form.month_days" multiple style="width: 100%">
                <el-option v-for="d in 31" :key="d" :label="d" :value="d" />
              </el-select>
              <div class="muted small">{{ t('insp.monthHint') }}</div>
            </el-form-item>
          </template>
          <template v-if="form.kind === 'yearly'">
            <el-form-item :label="t('insp.yearDates')">
              <div class="ypick">
                <el-select v-model="ym" style="width: 90px">
                  <el-option v-for="m in 12" :key="m" :label="locale === 'en' ? dayjs(new Date(2024, m - 1, 1)).format('MMM') : m" :value="m" />
                </el-select>
                <el-select v-model="yd" style="width: 80px">
                  <el-option v-for="d in daysIn(ym)" :key="d" :label="d" :value="d" />
                </el-select>
                <el-button @click="addYearDate">+</el-button>
              </div>
              <div class="ytags">
                <el-tag v-for="v in form.year_dates" :key="v" closable @close="form.year_dates = form.year_dates.filter((x) => x !== v)">{{ ymd(v) }}</el-tag>
                <span v-if="!form.year_dates.length" class="muted small">{{ t('insp.yearPick') }}</span>
              </div>
              <div class="muted small">{{ t('insp.yearHint') }}</div>
            </el-form-item>
            <el-form-item :label="t('insp.everyYears')"><el-input-number v-model="form.every_n" :min="1" :max="10" /></el-form-item>
          </template>
          <template v-if="form.kind === 'shift'">
            <el-form-item :label="t('insp.shiftKinds')">
              <el-checkbox-group v-model="form.shift_kinds">
                <el-checkbox-button v-for="k in ['day', 'middle', 'night']" :key="k" :value="k">{{ t(`shift.${k}`) }}</el-checkbox-button>
              </el-checkbox-group>
            </el-form-item>
            <el-form-item :label="t('insp.everyShifts')"><el-input-number v-model="form.every_n" :min="1" :max="365" /></el-form-item>
          </template>
          <el-form-item v-if="form.kind === 'daily'" :label="t('insp.everyDays')"><el-input-number v-model="form.every_n" :min="1" :max="365" /></el-form-item>
          <el-form-item v-if="form.kind !== 'shift'" :label="t('insp.atTime')">
            <el-time-select v-model="form.at_time" start="00:00" step="00:15" end="23:45" :clearable="false" style="width: 130px" />
          </el-form-item>
          <el-form-item v-if="['daily', 'shift', 'yearly'].includes(form.kind)" :label="t('insp.startDate')">
            <el-date-picker v-model="form.start_date" value-format="YYYY-MM-DD" :clearable="false" style="width: 160px" />
          </el-form-item>

          <el-form-item :label="t('insp.assign')">
            <el-radio-group v-model="form.assign" :disabled="!auth.isAdmin">
              <el-radio value="on_duty">{{ t('insp.onDuty') }}</el-radio>
              <el-radio value="fixed">{{ t('insp.fixed') }}</el-radio>
            </el-radio-group>
          </el-form-item>
          <template v-if="form.assign === 'fixed'">
            <el-form-item :label="t('insp.team')">
              <el-select v-model="form.team_id" :disabled="!auth.isAdmin" style="width: 160px">
                <el-option v-for="tm2 in auth.teams" :key="tm2.id" :label="localName(tm2)" :value="tm2.id" />
              </el-select>
              <div class="muted small">{{ t('insp.fixedHint') }}</div>
            </el-form-item>
            <el-form-item :label="t('insp.workers')">
              <el-select v-model="form.worker_ids" multiple filterable style="width: 100%">
                <el-option v-for="w in teamWorkers" :key="w.id" :label="w.name" :value="w.id" />
              </el-select>
            </el-form-item>
          </template>
          <el-form-item :label="t('insp.enabled')"><el-switch v-model="form.enabled" /></el-form-item>
        </el-form>

        <aside class="pv">
          <h4>{{ t('insp.preview') }}</h4>
          <div v-if="previewErr" class="muted small">{{ previewErr }}</div>
          <div v-for="(o, i) in preview" :key="i" class="pvrow">
            <div><b>{{ o.at.slice(form.kind === 'yearly' ? 0 : 5, 16).replace('T', ' ') }}</b> <span class="muted small">{{ tm('insp.wd')[(dayjs(o.at).day() + 6) % 7] }}</span></div>
            <div class="small">{{ teamName(o.team_id) || '—' }} · <ShiftTag :kind="o.shift_kind" /> <span class="muted">{{ o.shift_date.slice(5) }}</span></div>
          </div>
        </aside>
      </div>
      <template #footer>
        <el-button @click="dlg = false">{{ t('common.cancel') }}</el-button>
        <el-button type="primary" :disabled="!form.name?.trim() || !form.content?.trim() || !!previewErr" @click="save">{{ t('common.save') }}</el-button>
      </template>
    </el-dialog>

    <el-drawer v-model="hist" :title="histOf ? `${t('insp.history')} · ${histOf.name}` : ''" :size="isNarrow() ? '100%' : '460px'" append-to-body>
      <div v-for="r in runs" :key="r.id" class="run">
        <div><b>{{ fmtFull(r.occurrence_at) }}</b> <el-tag :type="runType[r.status]" size="small">{{ t(`insp.st.${r.status}`) }}</el-tag></div>
        <div class="small muted">
          {{ r.team_id ? teamName(r.team_id) : '' }}
          <el-button v-if="r.task_id" link type="primary" size="small" @click="detailId = r.task_id; detailOpen = true">#{{ r.task_id }}</el-button>
          {{ r.note }}
        </div>
      </div>
    </el-drawer>
    <TaskDetail v-model="detailOpen" :task-id="detailId" />
  </div>
</template>

<style scoped>
.edit { display: grid; grid-template-columns: 1fr 210px; gap: 16px; }
@media (max-width: 640px) { .edit { grid-template-columns: 1fr; } }
.pv { background: #f5f7fa; border-radius: 8px; padding: 10px 12px; align-self: start; }
.pv h4 { margin: 0 0 8px; }
.pvrow { padding: 6px 0; border-bottom: 1px solid #ebeef5; }
.muted { color: #909399; }
.small { font-size: 12px; }
.hint { margin: -4px 0 10px; }
.ypick { display: flex; gap: 6px; }
.ytags { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 6px; width: 100%; }
.run { padding: 8px 0; border-bottom: 1px solid #f2f3f5; }
.f :deep(.el-checkbox-button__inner) { padding: 6px 10px; }
</style>
