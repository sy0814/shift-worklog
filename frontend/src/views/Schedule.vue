<script setup>
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { ElMessage } from 'element-plus'
import dayjs from 'dayjs'
import api from '../api'
import { localName } from '../i18n'
import { useAuth } from '../stores/auth'
import ShiftTag from './ShiftTag.vue'

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
const newHoliday = reactive({ day: '', name: '' })
async function loadHolidays() {
  holidays.value = (await api.get('/holidays', { params: { year: year.value } })).data
}
async function addHoliday() {
  if (!newHoliday.day) return
  await api.put(`/holidays/${newHoliday.day}`, { ...newHoliday })
  newHoliday.day = newHoliday.name = ''
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
        </div>
        <el-table :data="days" size="small" border :row-class-name="({ row }) => (row.day === todayStr ? 'is-today' : '')">
          <el-table-column :label="t('schedule.date')" width="110" fixed>
            <template #default="{ row }">{{ row.day.slice(5) }} <small :class="{ weekend: !row.workday }">{{ weekday(row.day) }}</small></template>
          </el-table-column>
          <el-table-column v-for="team in auth.teams" :key="team.id" :label="localName(team)" min-width="90" align="center">
            <template #default="{ row }"><ShiftTag :kind="row.shifts[team.id]" /></template>
          </el-table-column>
        </el-table>
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
          <el-input v-model="newHoliday.name" :placeholder="t('schedule.holidayName')" style="width: 200px" />
          <el-button type="primary" @click="addHoliday">{{ t('common.add') }}</el-button>
        </div>
        <el-table :data="holidays" size="small" style="max-width: 520px">
          <el-table-column prop="day" :label="t('schedule.date')" width="130" />
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
:deep(.is-today) td { background: #ecf5ff !important; font-weight: 600; }
</style>
