<script setup>
// 设备统计（设备台账页的「统计」）：一段时间里每台设备的故障、检修、巡查次数，平均多久修好，哪些反复出问题。
// 一件事移交几次也只算一次（后端按移交链计数，见 backend/app/equipment_stats.py）。点设备看它的每件事和班次日志。
import { computed, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import dayjs from 'dayjs'
import api, { download } from '../api'
import { localText } from '../i18n'
import { fmtTime, isNarrow, STATUS_TYPE } from '../format'
import { useAuth } from '../stores/auth'
import TransText from './TransText.vue'
import TaskDetail from './TaskDetail.vue'
import ShiftTag from './ShiftTag.vue'

const { t, locale } = useI18n()
const auth = useAuth()
const range = ref([dayjs().subtract(89, 'day').format('YYYY-MM-DD'), dayjs().format('YYYY-MM-DD')])
const data = ref(null)
const loading = ref(false)

async function load() {
  loading.value = true
  try {
    data.value = (await api.get('/equipment-stats', { params: { start: range.value[0], end: range.value[1] } })).data
  } finally {
    loading.value = false
  }
}
onMounted(load)
function quick(days) {
  range.value = [dayjs().subtract(days - 1, 'day').format('YYYY-MM-DD'), dayjs().format('YYYY-MM-DD')]
  load()
}

const name = (e) => localText(e.name, e.source_lang).text || ''
const area = (e) => localText(e.area, e.source_lang).text || ''
const items = computed(() => data.value?.items || [])
const sum = (k) => items.value.reduce((a, x) => a + x[k], 0)
const tiles = computed(() => [
  { label: t('eqs.faults'), value: sum('fault') },
  { label: t('eqs.repeatCount'), value: items.value.filter((x) => x.repeat).length, warn: items.value.some((x) => x.repeat) },
  { label: t('eqs.openAll'), value: sum('open') },
  { label: t('eqs.idle'), value: data.value?.idle ?? 0 },
])
// 故障次数前 10（一个系列：一种颜色，不要图例，数字写在条的末端）
const top = computed(() => items.value.filter((x) => x.fault > 0).slice(0, 10))
const maxFault = computed(() => Math.max(1, ...top.value.map((x) => x.fault)))
const barTip = (x) => `${x.equipment.code} ${name(x.equipment)}\n${t('task.kinds.fault')} ${x.fault} · ${t('task.kinds.maintenance')} ${x.maintenance} · ${t('task.kinds.inspection')} ${x.inspection}`
  + (x.avg_hours != null ? `\n${t('eqs.avg')} ${x.avg_hours} h` : '')

// 某台设备的时间线
const tlOpen = ref(false)
const tlEq = ref(null)
const tl = ref([])
const tlLoading = ref(false)
async function openTimeline(row) {
  tlEq.value = row.equipment
  tl.value = []
  tlOpen.value = true
  tlLoading.value = true
  try {
    tl.value = (await api.get(`/equipment-stats/${row.equipment.id}/timeline`, { params: { start: range.value[0], end: range.value[1] } })).data
  } finally {
    tlLoading.value = false
  }
}
const detailOpen = ref(false)
const detailId = ref(null)
const KIND_TYPE = { fault: 'danger', maintenance: 'warning', inspection: 'success', other: 'info' }
</script>

<template>
  <div class="eq-stats">
    <div class="toolbar">
      <el-date-picker v-model="range" type="daterange" value-format="YYYY-MM-DD" :clearable="false" style="width: 260px" @change="load" />
      <el-button-group>
        <el-button v-for="d in [30, 90, 365]" :key="d" size="small" @click="quick(d)">{{ t('eqs.lastDays', { n: d }) }}</el-button>
      </el-button-group>
      <span class="spacer" />
      <el-button @click="download('/equipment-stats/xlsx', { start: range[0], end: range[1], lang: locale }, `equipment-stats-${range[0]}-${range[1]}.xlsx`)">{{ t('eq.export') }}</el-button>
    </div>
    <div class="muted small hint">{{ t('eqs.hint', { d: data?.repeat_days ?? 30, n: data?.repeat_n ?? 3 }) }}</div>

    <div v-loading="loading" class="body">
      <template v-if="data">
        <div class="tiles">
          <div v-for="x in tiles" :key="x.label" class="tile">
            <div class="tv">{{ x.value }}<span v-if="x.warn" class="warn-ic">⚠</span></div>
            <div class="tl muted">{{ x.label }}</div>
          </div>
        </div>

        <h4>{{ t('eqs.topTitle') }}</h4>
        <div v-if="!top.length" class="muted small">{{ t('eqs.noFaults') }}</div>
        <div v-for="x in top" :key="x.equipment.id" class="bar-row" :title="barTip(x)" @click="openTimeline(x)">
          <div class="bar-label"><b>{{ x.equipment.code }}</b> <span class="muted">{{ name(x.equipment) }}</span></div>
          <div class="bar-track">
            <div class="bar" :style="{ width: `calc((100% - 96px) * ${x.fault / maxFault})` }" />
            <span class="bar-val">{{ x.fault }}</span>
            <el-tag v-if="x.repeat" size="small" type="warning" effect="plain" class="rep">⚠ {{ t('eqs.repeat') }}</el-tag>
          </div>
        </div>

        <h4>{{ t('eqs.tableTitle') }}</h4>
        <el-table :data="items" size="small" border :default-sort="{ prop: 'fault', order: 'descending' }" class="tbl" @row-click="openTimeline">
          <el-table-column :label="t('eq.one')" min-width="170" fixed>
            <template #default="{ row }">
              <b>{{ row.equipment.code }}</b> {{ name(row.equipment) }}
              <div class="muted small">{{ area(row.equipment) }}</div>
            </template>
          </el-table-column>
          <el-table-column prop="fault" :label="t('task.kinds.fault')" width="90" sortable align="center" />
          <el-table-column prop="maintenance" :label="t('task.kinds.maintenance')" width="96" sortable align="center" />
          <el-table-column prop="inspection" :label="t('task.kinds.inspection')" width="80" sortable align="center" />
          <el-table-column prop="other" :label="t('task.kinds.other')" width="70" sortable align="center" />
          <el-table-column prop="open" :label="t('eqs.open')" width="96" sortable align="center">
            <template #default="{ row }">{{ row.open }}<span v-if="row.overdue" class="overdue"> ({{ t('eqs.overdueN', { n: row.overdue }) }})</span></template>
          </el-table-column>
          <el-table-column prop="avg_hours" :label="t('eqs.avg')" width="110" sortable align="center">
            <template #default="{ row }">{{ row.avg_hours ?? '–' }}</template>
          </el-table-column>
          <el-table-column prop="work_hours" :label="t('eqs.workHours')" width="100" sortable align="center" />
          <el-table-column prop="handovers" :label="t('eqs.handovers')" width="80" sortable align="center" />
          <el-table-column prop="logs" :label="t('tlog.title')" width="90" sortable align="center" />
          <el-table-column prop="last_at" :label="t('eqs.last')" width="110" sortable>
            <template #default="{ row }">{{ fmtTime(row.last_at) }}</template>
          </el-table-column>
          <el-table-column :label="t('eqs.repeat')" width="110" align="center" fixed="right">
            <template #default="{ row }"><el-tag v-if="row.repeat" size="small" type="warning" effect="plain">⚠ {{ t('eqs.repeatMax', { n: row.repeat_max }) }}</el-tag></template>
          </el-table-column>
        </el-table>
      </template>
    </div>

    <el-drawer v-model="tlOpen" :title="tlEq ? `${tlEq.code} · ${name(tlEq)}` : ''" :size="isNarrow() ? '100%' : '600px'" append-to-body>
      <div v-loading="tlLoading" class="tl-body">
        <div v-if="!tlLoading && !tl.length" class="muted">{{ t('eq.noTasks') }}</div>
        <div v-for="c in tl" :key="c.task_id" class="ev">
          <div class="ev-head">
            <span>{{ fmtTime(c.started_at) }}</span>
            <el-tag size="small" :type="KIND_TYPE[c.kind]" effect="plain">{{ t('task.kinds.' + c.kind) }}</el-tag>
            <el-tag size="small" :type="STATUS_TYPE[c.status]">{{ t('status.' + c.status) }}</el-tag>
            <span class="muted">{{ c.team_ids.map((id) => auth.teamLabel(id)).join(' → ') }}</span>
            <span v-if="c.hours != null" class="muted">{{ t('eqs.fixedIn', { h: c.hours }) }}</span>
            <el-button link type="primary" size="small" class="open" @click="detailId = c.last_task_id; detailOpen = true">#{{ c.last_task_id }}</el-button>
          </div>
          <TransText :tri="c.content" :src-lang="c.source_lang" field="content" compact />
          <div v-for="(x, i) in c.logs" :key="i" class="log">
            <div class="muted small"><ShiftTag :kind="x.shift_kind" /> {{ x.shift_date.slice(5) }} · {{ x.author }} · {{ fmtTime(x.recorded_at) }}</div>
            <TransText :tri="x.content" :src-lang="x.source_lang" field="log" compact />
          </div>
        </div>
      </div>
    </el-drawer>
    <TaskDetail v-model="detailOpen" :task-id="detailId" />
  </div>
</template>

<style scoped>
.toolbar { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }
.spacer { flex: 1; }
.hint { margin: 6px 0 10px; }
.small { font-size: 12px; }
.muted { color: #909399; }
.body { min-height: 200px; }
.tiles { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 10px; }
@media (max-width: 640px) { .tiles { grid-template-columns: repeat(2, minmax(0, 1fr)); } }
.tile { padding: 12px 14px; border: 1px solid var(--el-border-color-lighter); border-radius: 8px; background: var(--el-bg-color); }
.tv { font-size: 26px; font-weight: 600; line-height: 1.2; color: var(--el-text-color-primary); }
.warn-ic { font-size: 16px; margin-left: 6px; color: var(--el-color-warning); }
.tl { font-size: 12px; margin-top: 2px; }
h4 { margin: 18px 0 8px; }
.bar-row { display: grid; grid-template-columns: minmax(120px, 34%) 1fr; gap: 10px; align-items: center; padding: 4px 6px; border-radius: 4px; cursor: pointer; }
.bar-row:hover { background: var(--el-fill-color-light); }
.bar-label { white-space: nowrap; overflow: hidden; text-overflow: ellipsis; font-size: 13px; }
.bar-track { display: flex; align-items: center; gap: 6px; min-width: 0; }
.bar { height: 14px; min-width: 4px; background: var(--el-color-primary); border-radius: 0 4px 4px 0; }
.bar-val { font-size: 12px; color: var(--el-text-color-regular); font-variant-numeric: tabular-nums; }
.rep { flex: none; }
.tbl { width: 100%; cursor: pointer; }
.overdue { color: var(--el-color-danger); font-size: 12px; }
.ev { padding: 10px 12px; border: 1px solid var(--el-border-color-lighter); border-radius: 6px; margin-bottom: 10px; }
.ev-head { display: flex; flex-wrap: wrap; align-items: center; gap: 6px; font-size: 12px; margin-bottom: 4px; }
.open { margin-left: auto; }
.log { margin: 6px 0 0 10px; padding-left: 8px; border-left: 2px solid var(--el-border-color); }
</style>
