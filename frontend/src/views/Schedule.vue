<script setup>
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { ElMessage } from 'element-plus'
import dayjs from 'dayjs'
import api from '../api'
import { localName } from '../i18n'
import { useAuth } from '../stores/auth'
import ShiftTag from '../components/ShiftTag.vue'

const { t, tm, locale } = useI18n()
const auth = useAuth()

const month = ref(dayjs().format('YYYY-MM'))
const days = ref([])
const todayStr = dayjs().format('YYYY-MM-DD')
const WEEK = { zh: '日一二三四五六', sr: ['ned', 'pon', 'uto', 'sre', 'čet', 'pet', 'sub'], en: ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'] }
const weekday = (d) => WEEK[locale.value][dayjs(d).day()]

async function loadCalendar() {
  const m = dayjs(month.value + '-01')
  days.value = (await api.get('/shifts/calendar', {
    params: { start: m.format('YYYY-MM-DD'), end: m.endOf('month').format('YYYY-MM-DD') },
  })).data
}
watch(month, loadCalendar)

// ---- 管理员：班组整体调班 ----
const changes = computed(() => days.value.flatMap((d) => Object.entries(d.changed || {}).map(([tid, was]) => (
  { day: d.day, team_id: Number(tid), shift: d.shifts[tid], was }))))
const tsOpen = ref(false)
const ts = reactive({ team_id: null, range: [], shift_kind: 'day', note: '' })
function openTeamShift(teamId, day) {
  if (!auth.isAdmin) return
  const d = day || todayStr
  const cur = days.value.find((x) => x.day === d)
  Object.assign(ts, { team_id: teamId ?? auth.teams[0]?.id, range: [d, d],
    shift_kind: (cur && teamId && cur.shifts[teamId]) || 'day', note: '' })
  tsOpen.value = true
}
async function saveTeamShift() {
  await api.put('/team-shifts', { team_id: ts.team_id, start: ts.range[0], end: ts.range[1], shift_kind: ts.shift_kind, note: ts.note })
  tsOpen.value = false
  ElMessage.success(t('common.saved'))
  loadCalendar()
}
async function restoreTeamShift(teamId, start, end) {
  await api.delete('/team-shifts', { params: { team_id: teamId, start, end } })
  tsOpen.value = false
  ElMessage.success(t('common.saved'))
  loadCalendar()
}

// ---- 管理员：排班基准 ----
const rotating = computed(() => auth.teams.filter((x) => x.kind === 'rotating'))
const cfg = reactive({ base_date: '', day_start: '', middle_start: '', night_start: '', offsets: {} })
async function loadConfig() {
  const c = (await api.get('/shifts/config')).data
  Object.assign(cfg, c, {
    day_start: c.day_start.slice(0, 5), middle_start: c.middle_start.slice(0, 5), night_start: c.night_start.slice(0, 5),
    offsets: Object.fromEntries(rotating.value.map((x) => [x.id, x.cycle_offset])) })
}
async function saveConfig() {
  await api.put('/shifts/config', cfg)
  await auth.loadTeams()
  await loadCalendar()
  ElMessage.success(t('common.saved'))
}

// ---- 管理员：节假日 ----
const year = ref(dayjs().year())
const holidays = ref([])
const newHoliday = reactive({ day: '', name: '', kind: 'holiday' })
async function loadHolidays() {
  holidays.value = (await api.get('/holidays', { params: { year: year.value } })).data
}
async function addHoliday() {
  if (!newHoliday.day) return
  await api.put(`/holidays/${newHoliday.day}`, { ...newHoliday })
  newHoliday.day = newHoliday.name = ''
  newHoliday.kind = 'holiday'
  await Promise.all([loadHolidays(), loadCalendar()])
}
async function removeHoliday(day) {
  await api.delete(`/holidays/${day}`)
  await Promise.all([loadHolidays(), loadCalendar()])
}
watch(year, loadHolidays)

onMounted(async () => {
  await loadCalendar()
  if (auth.isAdmin) await Promise.all([loadConfig(), loadHolidays()])
})
</script>

<template>
  <div class="page">
    <el-tabs>
      <el-tab-pane :label="t('schedule.calendar')">
        <div class="toolbar">
          <el-date-picker v-model="month" type="month" value-format="YYYY-MM" :clearable="false" />
          <el-button v-if="auth.isAdmin" type="primary" plain @click="openTeamShift(null)">{{ t('schedule.teamShift') }}</el-button>
          <span v-if="auth.isAdmin" class="muted">{{ t('schedule.clickHint') }}</span>
        </div>
        <el-table :data="days" size="small" border :row-class-name="({ row }) => (row.day === todayStr ? 'is-today' : '')">
          <el-table-column :label="t('schedule.date')" width="110" fixed>
            <template #default="{ row }">{{ row.day.slice(5) }} <small :class="{ weekend: !row.workday }">{{ weekday(row.day) }}</small></template>
          </el-table-column>
          <el-table-column v-for="team in auth.teams" :key="team.id" :label="localName(team)" min-width="90" align="center">
            <template #default="{ row }">
              <span :class="['cell', { admin: auth.isAdmin, changed: row.changed?.[team.id] }]" @click="openTeamShift(team.id, row.day)">
                <ShiftTag :kind="row.shifts[team.id]" />
                <small v-if="row.changed?.[team.id]" class="was">{{ t('schedule.changedFrom', { s: t('shift.' + row.changed[team.id]) }) }}</small>
              </span>
            </template>
          </el-table-column>
        </el-table>
        <template v-if="changes.length">
          <h4>{{ t('schedule.listTitle') }}</h4>
          <el-table :data="changes" size="small" style="max-width: 640px">
            <el-table-column prop="day" :label="t('schedule.date')" width="120" />
            <el-table-column :label="t('task.team')" width="100"><template #default="{ row }">{{ localName(auth.teamById(row.team_id)) }}</template></el-table-column>
            <el-table-column :label="t('schedule.shiftTo')"><template #default="{ row }"><ShiftTag :kind="row.shift" /> <small class="muted">{{ t('schedule.changedFrom', { s: t('shift.' + row.was) }) }}</small></template></el-table-column>
            <el-table-column v-if="auth.isAdmin" width="130">
              <template #default="{ row }"><el-button link type="primary" @click="restoreTeamShift(row.team_id, row.day, row.day)">{{ t('schedule.restore') }}</el-button></template>
            </el-table-column>
          </el-table>
        </template>

        <el-dialog v-model="tsOpen" :title="t('schedule.teamShift')" width="min(480px, 94vw)" append-to-body>
          <p class="muted">{{ t('schedule.teamShiftHint') }}</p>
          <el-form label-width="auto">
            <el-form-item :label="t('task.team')">
              <el-select v-model="ts.team_id"><el-option v-for="tm2 in auth.teams" :key="tm2.id" :label="localName(tm2)" :value="tm2.id" /></el-select>
            </el-form-item>
            <el-form-item :label="t('schedule.range')">
              <el-date-picker v-model="ts.range" type="daterange" value-format="YYYY-MM-DD" :clearable="false" style="width: 100%" />
            </el-form-item>
            <el-form-item :label="t('schedule.shiftTo')">
              <el-radio-group v-model="ts.shift_kind">
                <el-radio-button v-for="k in ['day', 'middle', 'night', 'off']" :key="k" :value="k">{{ t('shift.' + k) }}</el-radio-button>
              </el-radio-group>
            </el-form-item>
            <el-form-item :label="t('schedule.note')"><el-input v-model="ts.note" maxlength="200" /></el-form-item>
          </el-form>
          <template #footer>
            <el-button @click="restoreTeamShift(ts.team_id, ts.range[0], ts.range[1])">{{ t('schedule.restore') }}</el-button>
            <el-button type="primary" :disabled="!ts.team_id || !ts.range?.length" @click="saveTeamShift">{{ t('common.save') }}</el-button>
          </template>
        </el-dialog>
      </el-tab-pane>

      <el-tab-pane v-if="auth.isAdmin" :label="t('schedule.config')">
        <el-form label-width="auto" style="max-width: 520px">
          <el-form-item :label="t('schedule.baseDate')">
            <el-date-picker v-model="cfg.base_date" value-format="YYYY-MM-DD" :clearable="false" />
          </el-form-item>
          <el-form-item v-for="team in rotating" :key="team.id" :label="`${localName(team)} · ${t('schedule.offset')}`">
            <el-select v-model="cfg.offsets[team.id]" style="width: 120px">
              <el-option v-for="(p, i) in tm('schedule.pos')" :key="i" :label="p" :value="i" />
            </el-select>
          </el-form-item>
          <el-form-item :label="t('schedule.dayStart')"><el-time-select v-model="cfg.day_start" start="00:00" step="00:30" end="23:30" format="HH:mm" /></el-form-item>
          <el-form-item :label="t('schedule.middleStart')"><el-time-select v-model="cfg.middle_start" start="00:00" step="00:30" end="23:30" format="HH:mm" /></el-form-item>
          <el-form-item :label="t('schedule.nightStart')"><el-time-select v-model="cfg.night_start" start="00:00" step="00:30" end="23:30" format="HH:mm" /></el-form-item>
          <el-form-item><el-button type="primary" @click="saveConfig">{{ t('common.save') }}</el-button></el-form-item>
        </el-form>
      </el-tab-pane>

      <el-tab-pane v-if="auth.isAdmin" :label="t('schedule.holidays')">
        <div class="toolbar">
          <el-input-number v-model="year" :min="2020" :max="2100" controls-position="right" />
          <el-date-picker v-model="newHoliday.day" value-format="YYYY-MM-DD" :placeholder="t('schedule.date')" />
          <el-select v-model="newHoliday.kind" style="width: 150px">
            <el-option value="holiday" :label="t('schedule.kindHoliday')" />
            <el-option value="workday" :label="t('schedule.kindWorkday')" />
          </el-select>
          <el-input v-model="newHoliday.name" :placeholder="t('schedule.holidayName')" style="width: 200px" />
          <el-button type="primary" @click="addHoliday">{{ t('common.add') }}</el-button>
        </div>
        <el-table :data="holidays" size="small" style="max-width: 520px">
          <el-table-column prop="day" :label="t('schedule.date')" width="130" />
          <el-table-column width="130">
            <template #default="{ row }">
              <el-tag :type="row.kind === 'workday' ? 'warning' : 'success'" size="small">{{ row.kind === 'workday' ? t('schedule.kindWorkday') : t('schedule.kindHoliday') }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column prop="name" :label="t('schedule.holidayName')" />
          <el-table-column width="90">
            <template #default="{ row }"><el-button link type="danger" @click="removeHoliday(row.day)">{{ t('common.delete') }}</el-button></template>
          </el-table-column>
        </el-table>
      </el-tab-pane>
    </el-tabs>
  </div>
</template>

<style scoped>
.weekend { color: #f56c6c; }
.toolbar { display: flex; gap: 10px; align-items: center; flex-wrap: wrap; margin-bottom: 8px; }
.cell { display: inline-flex; flex-direction: column; align-items: center; gap: 1px; }
.cell.admin { cursor: pointer; }
.cell.changed :deep(.el-tag) { outline: 2px dashed #e6a23c; outline-offset: 1px; }
.was { color: #e6a23c; font-size: 11px; }
.muted { color: #909399; font-size: 13px; }
:deep(.is-today) td { background: #ecf5ff !important; font-weight: 600; }
</style>
