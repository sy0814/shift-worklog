<script setup>
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { ElMessage, ElMessageBox } from 'element-plus'
import dayjs from 'dayjs'
import api from '../api'
import { localName } from '../i18n'
import { isNarrow } from '../format'
import { useAuth } from '../stores/auth'
import ShiftTag from '../components/ShiftTag.vue'
import CycleEditor from '../components/CycleEditor.vue'
import TriNames from '../components/TriNames.vue'
import { fullHours, shortEntry } from '../cycle'

const { t, tm, locale } = useI18n()
const auth = useAuth()

const month = ref(dayjs().format('YYYY-MM'))
const days = ref([])
const todayStr = dayjs().format('YYYY-MM-DD')
const WEEK = { zh: '日一二三四五六', sr: ['ned', 'pon', 'uto', 'sre', 'čet', 'pet', 'sub'], en: ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'] }
const weekday = (d) => WEEK[locale.value][dayjs(d).day()]

const coverage = ref([])
const narrow = isNarrow() // 手机上日历列宽固定，免得加载后再算一次列宽（表头左右跳）
async function loadCalendar() {
  const m = dayjs(month.value + '-01')
  const params = { start: m.format('YYYY-MM-DD'), end: m.endOf('month').format('YYYY-MM-DD') }
  const [c, cov] = await Promise.all([api.get('/shifts/calendar', { params }), api.get('/shifts/coverage', { params })])
  days.value = c.data
  coverage.value = cov.data
  // 表格第一次画出来时列宽还没算好（手机上会先窄后宽地跳一下）：等两帧算好列宽再显示
  if (!calReady.value) requestAnimationFrame(() => requestAnimationFrame(() => { calReady.value = true }))
}
const calReady = ref(false)
// 排班提醒：某个班次没有班组上 / 两个主班组同时上
const covText = (p) => {
  const d = `${p.day.slice(5)} ${weekday(p.day)}`
  const sh = t('shift.' + p.shift_kind)
  return p.problem === 'none' ? t('schedule.covNone', { d, s: sh })
    : t('schedule.covMulti', { d, s: sh, teams: p.team_ids.map((id) => localName(auth.teamById(id))).join(' + ') })
}
const covAt = computed(() => new Set(coverage.value.filter((p) => p.problem === 'none').map((p) => p.day)))
// 临时班组有效期以外显示为「未启用」
const teamActive = (team, day) => (!team.active_from || day >= team.active_from) && (!team.active_to || day <= team.active_to)
watch(month, loadCalendar)

// ---- 班组调班：管理员任何班组；班长本班组（临时调班），或和别的班组互换 ----
const changes = computed(() => days.value.flatMap((d) => Object.entries(d.changed || {}).map(([tid, was]) => (
  { day: d.day, team_id: Number(tid), shift: d.shifts[tid], was }))))
const tsOpen = ref(false)
const canShift = (teamId) => auth.teamOk('schedule.team_shift', teamId)
const canShiftAny = computed(() => auth.can('schedule.team_shift'))
const ts = reactive({ mode: 'set', team_id: null, team_b: null, range: [], shift_kind: 'day', note: '' })
function openTeamShift(teamId, day) {
  if (teamId != null && !canShift(teamId)) return
  if (!canShiftAny.value) return
  const d = day || todayStr
  const cur = days.value.find((x) => x.day === d)
  const team = teamId ?? (auth.isAdmin ? auth.teams[0]?.id : auth.user.team_id)
  Object.assign(ts, { mode: 'set', team_id: team, team_b: null, range: [d, d],
    shift_kind: (cur && teamId && cur.shifts[teamId]) || 'day', note: '' })
  tsOpen.value = true
}
async function saveTeamShift() {
  const [start, end] = ts.range
  if (ts.mode === 'swap') {
    await api.post('/team-shifts/swap', { team_a: ts.team_id, team_b: ts.team_b, start, end, note: ts.note })
  } else {
    await api.put('/team-shifts', { team_id: ts.team_id, start, end, shift_kind: ts.shift_kind, note: ts.note })
  }
  tsOpen.value = false
  await loadCalendar()
  await warnCoverage(start, end)
}
// 保存后检查这几天有没有班次没人上（月份外的日子也查）
async function warnCoverage(start, end) {
  const probs = (await api.get('/shifts/coverage', { params: { start, end } })).data
  if (!probs.length) return ElMessage.success(t('common.saved'))
  ElMessageBox.alert(probs.map(covText).join('\n'), t('schedule.covAfter'), { type: 'warning', customStyle: { whiteSpace: 'pre-line' } })
}
async function restoreTeamShift(teamId, start, end) {
  await api.delete('/team-shifts', { params: { team_id: teamId, start, end } })
  tsOpen.value = false
  ElMessage.success(t('common.saved'))
  loadCalendar()
}

// ---- 管理员：班次时间（各班组的循环在「班组管理」里设置）----
const cfg = reactive({ day_start: '', middle_start: '', night_start: '' })
async function loadConfig() {
  const c = (await api.get('/shifts/config')).data
  Object.assign(cfg, { day_start: c.day_start.slice(0, 5), middle_start: c.middle_start.slice(0, 5), night_start: c.night_start.slice(0, 5) })
}
async function saveConfig() {
  await api.put('/shifts/config', cfg)
  await auth.loadTeams()
  await loadCalendar()
  ElMessage.success(t('common.saved'))
}

// ---- 管理员：班组管理（新增长期 / 临时班组） ----
const teamDlg = ref(false)
const teamEditing = ref(null)
const tf = reactive({})
// 循环的简短写法：「白白中中夜夜休休（8 天）」
const cycleText = (team) => (team.kind === 'cycle' && team.pattern
  ? `${team.pattern.map((k) => shortEntry(k, t)).join(' ')}（${team.pattern.length}）` : t('schedule.kindShort.manual'))
function openTeam(team) {
  teamEditing.value = team || null
  Object.assign(tf, team
    ? { name_zh: team.name_zh, name_sr: team.name_sr, name_en: team.name_en, kind: team.kind, is_main: team.is_main,
        cyc: { pattern: [...(team.pattern || ['day', 'day', 'middle', 'middle', 'night', 'night', 'off', 'off'])],
          cycle_start: team.cycle_start || todayStr, holiday_off: team.holiday_off },
        temporary: !!(team.active_from || team.active_to), active_from: team.active_from, active_to: team.active_to }
    : { name_zh: '', name_sr: '', name_en: '', kind: 'cycle', is_main: false,
        cyc: { pattern: ['day', 'day', 'middle', 'middle', 'night', 'night', 'off', 'off'], cycle_start: todayStr, holiday_off: false },
        temporary: false, active_from: todayStr, active_to: null })
  teamDlg.value = true
}
async function saveTeam() {
  const body = { name_zh: tf.name_zh, name_sr: tf.name_sr, name_en: tf.name_en, kind: tf.kind, is_main: tf.is_main,
    ...(tf.kind === 'cycle' ? { pattern: tf.cyc.pattern, cycle_start: tf.cyc.cycle_start, holiday_off: tf.cyc.holiday_off } : {}),
    active_from: tf.temporary ? tf.active_from : null, active_to: tf.temporary ? tf.active_to : null }
  if (teamEditing.value) await api.put(`/teams/${teamEditing.value.id}`, body)
  else await api.post('/teams', body)
  teamDlg.value = false
  await auth.loadTeams()
  await Promise.all([loadCalendar(), loadConfig()])
  ElMessage.success(t('common.saved'))
}
async function deleteTeam(team) {
  await ElMessageBox.confirm(t('schedule.teamUsedHint'), t('schedule.teamDelConfirm', { n: localName(team) }), { type: 'warning' })
  await api.delete(`/teams/${team.id}`)
  await auth.loadTeams()
  await Promise.all([loadCalendar(), loadConfig()])
  ElMessage.success(t('common.saved'))
}
const periodText = (team) => (team.active_from || team.active_to
  ? `${team.active_from || '…'} ~ ${team.active_to || '…'}` : t('schedule.longTerm'))

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
          <el-button v-if="canShiftAny" type="primary" plain @click="openTeamShift(null)">{{ t('schedule.teamShift') }}</el-button>
          <span v-if="canShiftAny" class="muted">{{ t('schedule.clickHint') }}</span>
        </div>
        <el-alert v-if="coverage.length" type="warning" :closable="false" show-icon class="cov" :title="t('schedule.covTitle')">
          <div v-for="(p, i) in coverage.slice(0, 8)" :key="i">{{ covText(p) }}</div>
          <div v-if="coverage.length > 8">…（{{ coverage.length }}）</div>
        </el-alert>
        <el-table :data="days" size="small" border :class="['cal', { hidden: !calReady }]" :row-class-name="({ row }) => [row.day === todayStr ? 'is-today' : '', covAt.has(row.day) ? 'is-gap' : ''].join(' ')">
          <el-table-column :label="t('schedule.date')" :width="narrow ? 86 : 110" fixed>
            <template #default="{ row }">{{ row.day.slice(5) }} <small :class="{ weekend: !row.workday }">{{ weekday(row.day) }}</small></template>
          </el-table-column>
          <el-table-column v-for="team in auth.teams" :key="team.id" :label="localName(team)" :width="narrow ? 84 : undefined" min-width="90" align="center">
            <template #default="{ row }">
              <span :class="['cell', { admin: canShift(team.id), changed: row.changed?.[team.id] }]" @click="openTeamShift(team.id, row.day)">
                <ShiftTag v-if="teamActive(team, row.day)" :kind="row.shifts[team.id]" />
                <small v-else class="muted">{{ t('schedule.inactive') }}</small>
                <small v-if="row.hours?.[team.id]" class="hrs" :title="fullHours(row.hours[team.id])">{{ shortEntry(row.hours[team.id], t) }}</small>
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
            <el-table-column v-if="canShiftAny" width="130">
              <template #default="{ row }"><el-button v-if="canShift(row.team_id)" link type="primary" @click="restoreTeamShift(row.team_id, row.day, row.day)">{{ t('schedule.restore') }}</el-button></template>
            </el-table-column>
          </el-table>
        </template>

        <el-dialog v-model="tsOpen" :title="t('schedule.teamShift')" width="min(480px, 94vw)" append-to-body>
          <p class="muted">{{ t('schedule.teamShiftHint') }}</p>
          <el-form label-width="auto">
            <el-form-item>
              <el-radio-group v-model="ts.mode">
                <el-radio-button value="set">{{ t('schedule.mode.set') }}</el-radio-button>
                <el-radio-button value="swap">{{ t('schedule.mode.swap') }}</el-radio-button>
              </el-radio-group>
            </el-form-item>
            <el-form-item :label="t('task.team')">
              <el-select v-model="ts.team_id" :disabled="auth.scope('schedule.team_shift') !== 'all'"><el-option v-for="tm2 in auth.teams" :key="tm2.id" :label="localName(tm2)" :value="tm2.id" /></el-select>
            </el-form-item>
            <el-form-item v-if="ts.mode === 'swap'" :label="t('schedule.teamB')">
              <el-select v-model="ts.team_b"><el-option v-for="tm2 in auth.teams.filter((x) => x.id !== ts.team_id)" :key="tm2.id" :label="localName(tm2)" :value="tm2.id" /></el-select>
            </el-form-item>
            <el-form-item :label="t('schedule.range')">
              <el-date-picker v-model="ts.range" type="daterange" value-format="YYYY-MM-DD" :clearable="false" style="width: 100%" />
            </el-form-item>
            <el-form-item v-if="ts.mode === 'set'" :label="t('schedule.shiftTo')">
              <el-radio-group v-model="ts.shift_kind">
                <el-radio-button v-for="k in ['day', 'middle', 'night', 'off']" :key="k" :value="k">{{ t('shift.' + k) }}</el-radio-button>
              </el-radio-group>
            </el-form-item>
            <el-form-item :label="t('schedule.note')"><el-input v-model="ts.note" maxlength="200" /></el-form-item>
          </el-form>
          <template #footer>
            <el-button v-if="ts.mode === 'set'" @click="restoreTeamShift(ts.team_id, ts.range[0], ts.range[1])">{{ t('schedule.restore') }}</el-button>
            <el-button type="primary" :disabled="!ts.team_id || !ts.range?.length || (ts.mode === 'swap' && !ts.team_b)" @click="saveTeamShift">{{ t('common.save') }}</el-button>
          </template>
        </el-dialog>
      </el-tab-pane>

      <el-tab-pane v-if="auth.isAdmin" lazy :label="t('schedule.teams')">
        <div class="toolbar"><el-button type="primary" @click="openTeam(null)">{{ t('schedule.addTeam') }}</el-button></div>
        <!-- 列宽都固定：切到这个标签时表格不用再算一次列宽（否则会左右跳一下） -->
        <el-table :data="auth.teams" size="small" border class="teams-table">
          <el-table-column :label="t('schedule.teamName')" width="250">
            <template #default="{ row }"><b>{{ localName(row) }}</b> <small class="muted">{{ [row.name_zh, row.name_sr, row.name_en].filter((x) => x !== localName(row)).join(' / ') }}</small></template>
          </el-table-column>
          <el-table-column :label="t('schedule.isMain')" width="110">
            <template #default="{ row }"><el-tag v-if="row.is_main" size="small">{{ t('schedule.isMain') }}</el-tag><span v-else class="muted">{{ t('schedule.merged') }}</span></template>
          </el-table-column>
          <el-table-column :label="t('schedule.cycleCol')" width="300">
            <template #default="{ row }">
              <span class="cyctext">{{ cycleText(row) }}</span>
              <div v-if="row.kind === 'cycle'" class="muted small">{{ t('cyc.start') }} {{ row.cycle_start }}<template v-if="row.holiday_off"> · {{ t('schedule.holidayOffShort') }}</template></div>
            </template>
          </el-table-column>
          <el-table-column :label="t('schedule.period')" width="230">
            <template #default="{ row }"><el-tag v-if="row.active_from || row.active_to" type="warning" size="small">{{ t('schedule.temporary') }}</el-tag> {{ periodText(row) }}</template>
          </el-table-column>
          <el-table-column width="130">
            <template #default="{ row }">
              <el-button link type="primary" @click="openTeam(row)">{{ t('common.edit') }}</el-button>
              <el-button link type="danger" @click="deleteTeam(row)">{{ t('common.delete') }}</el-button>
            </template>
          </el-table-column>
        </el-table>
        <p class="muted">{{ t('schedule.teamUsedHint') }}</p>

        <el-dialog v-model="teamDlg" :title="teamEditing ? t('schedule.editTeam') : t('schedule.addTeam')" width="min(720px, 96vw)" :fullscreen="isNarrow()" append-to-body>
          <el-form label-width="auto">
            <el-form-item :label="t('schedule.teamName')">
              <TriNames v-model="tf" />
            </el-form-item>
            <el-form-item :label="t('schedule.isMain')">
              <div class="names">
                <el-switch v-model="tf.is_main" />
                <small class="muted">{{ t('schedule.isMainHint') }}</small>
              </div>
            </el-form-item>
            <el-form-item :label="t('schedule.kind')">
              <el-radio-group v-model="tf.kind" class="kinds">
                <el-radio v-for="k in ['cycle', 'manual']" :key="k" :value="k">{{ t('schedule.kinds.' + k) }}</el-radio>
              </el-radio-group>
            </el-form-item>
            <el-form-item v-if="tf.kind === 'cycle'" :label="t('schedule.cycleCol')">
              <CycleEditor v-model="tf.cyc" />
            </el-form-item>
            <p v-if="tf.kind === 'manual'" class="muted">{{ t('schedule.manualHint') }}</p>
            <el-form-item :label="t('schedule.temporary')"><el-switch v-model="tf.temporary" /></el-form-item>
            <el-form-item v-if="tf.temporary" :label="t('schedule.period')">
              <div class="names">
                <div class="row2">
                  <el-date-picker v-model="tf.active_from" value-format="YYYY-MM-DD" style="width: 150px" />
                  <span>~</span>
                  <el-date-picker v-model="tf.active_to" value-format="YYYY-MM-DD" style="width: 150px" />
                </div>
                <small class="muted">{{ t('schedule.openEnd') }}</small>
              </div>
            </el-form-item>
          </el-form>
          <template #footer>
            <el-button @click="teamDlg = false">{{ t('common.cancel') }}</el-button>
            <el-button type="primary" :disabled="!(tf.name_zh || tf.name_sr || tf.name_en)?.trim()" @click="saveTeam">{{ t('common.save') }}</el-button>
          </template>
        </el-dialog>
      </el-tab-pane>

      <el-tab-pane v-if="auth.isAdmin" lazy :label="t('schedule.config')">
        <el-form label-width="auto" style="max-width: 520px">
          <el-form-item :label="t('schedule.dayStart')"><el-time-select v-model="cfg.day_start" start="00:00" step="00:30" end="23:30" format="HH:mm" /></el-form-item>
          <el-form-item :label="t('schedule.middleStart')"><el-time-select v-model="cfg.middle_start" start="00:00" step="00:30" end="23:30" format="HH:mm" /></el-form-item>
          <el-form-item :label="t('schedule.nightStart')"><el-time-select v-model="cfg.night_start" start="00:00" step="00:30" end="23:30" format="HH:mm" /></el-form-item>
          <el-form-item><el-button type="primary" @click="saveConfig">{{ t('common.save') }}</el-button></el-form-item>
        </el-form>
      </el-tab-pane>

      <el-tab-pane v-if="auth.isAdmin" lazy :label="t('schedule.holidays')">
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
.hrs { color: #1d7a66; font-size: 11px; white-space: nowrap; }
.muted { color: #909399; font-size: 13px; }
:deep(.is-today) td { background: #ecf5ff !important; font-weight: 600; }
:deep(.is-gap) td:first-child { box-shadow: inset 3px 0 0 #e6a23c; }
.cov { margin-bottom: 8px; }
.names { display: flex; flex-direction: column; gap: 6px; width: 100%; }
.row2 { display: flex; gap: 6px; align-items: center; flex-wrap: wrap; }
.kinds { display: flex; flex-direction: column; align-items: flex-start; }
/* 日历表头不换行：手机上列宽算出来之前表头会先换行变高，再缩回去（表格往上跳） */
.cal :deep(th .cell) { white-space: nowrap; }
.cal.hidden { visibility: hidden; }
.teams-table { width: max-content; max-width: 100%; }
.cyctext { font-family: ui-monospace, Menlo, Consolas, monospace; letter-spacing: 1px; }
.small { font-size: 12px; }
</style>
