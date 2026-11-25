<script setup>
// 首页：未闭环警示 → 当前在班 / 下一个接班（含在岗人数，点开看人员状态）→ 今日排班（默认收起，
// 点里面的班组 = 在下面看它的交接班）→ 交接班（合并在首页）
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import dayjs from 'dayjs'
import api from '../api'
import { localName } from '../i18n'
import { useAuth } from '../stores/auth'
import { warmTasks } from '../offline'
import ShiftTag from '../components/ShiftTag.vue'
import TaskCard from '../components/TaskCard.vue'
import TaskDetail from '../components/TaskDetail.vue'
import TaskForm from '../components/TaskForm.vue'
import HandoverBoard from '../components/HandoverBoard.vue'
import DutyDrawer from '../components/DutyDrawer.vue'

const { t } = useI18n()
const auth = useAuth()
const now = ref(null)
const duty = ref({ current: null, next: null })
const overdue = ref([])
const today = ref(null)
const boardRef = ref()

async function load() {
  const [od, nw] = await Promise.all([api.get('/overdue'), api.get('/shifts/now')])
  overdue.value = od.data
  if (!od.headers['x-from-cache']) setTimeout(() => warmTasks(api, od.data.map((x) => x.id)), 2500) // 离线也能打开
  now.value = nw.data
  const d = now.value.current.shift_date
  const [cal, cur, nxt] = await Promise.all([
    api.get('/shifts/calendar', { params: { start: d, end: d } }),
    api.get('/duty', { params: { which: 'current' } }),
    api.get('/duty', { params: { which: 'next' } }),
  ])
  today.value = cal.data[0]
  duty.value = { current: cur.data, next: nxt.data }
}

let timer
onMounted(() => {
  load()
  timer = setInterval(load, 60_000)
})
onUnmounted(() => clearInterval(timer))

const fmt = (s) => dayjs(s.slice(0, 16)).format('MM-DD HH:mm')
// 卡片上显示这个班次合在一起的所有班组（主班组在前），和交接班里合并显示的一致
const mainTeam = (s) => [...s.team_ids].sort((a, b) => !!auth.teamById(b)?.is_main - !!auth.teamById(a)?.is_main)
  .map((id) => localName(auth.teamById(id))).join(' + ')
// 交接班看哪个班组：0 = 默认；在「今日排班」里点班组切换
const boardTeam = ref(0)
// 今日排班展开 / 收起：记在本机
const readOpen = () => { try { return localStorage.getItem('home_today_open') === '1' ? ['today'] : [] } catch { return [] } }
const todayOpen = ref(readOpen())
watch(todayOpen, (v) => { try { localStorage.setItem('home_today_open', v.length ? '1' : '0') } catch { /* 存不了就算了 */ } })
function viewTeam(id) {
  boardTeam.value = id
}
const cards = computed(() => now.value && [
  { key: 'current', s: now.value.current, d: duty.value.current },
  { key: 'next', s: now.value.next, d: duty.value.next },
])

// ---- 人员状态 / 快捷添加任务 ----
const dutyOpen = ref(false)
const dutyWhich = ref('current')
function openDuty(which) {
  dutyWhich.value = which
  dutyOpen.value = true
}
const formOpen = ref(false)
const preset = ref(null)
function quickAdd(p) {
  preset.value = p
  formOpen.value = true
}
const drawerRef = ref()
// 任务有变化（新建、改状态、移交……）：卡片人数、交接班、打开着的人员状态都刷新
function refreshAll() {
  load()
  boardRef.value?.load()
  if (dutyOpen.value) drawerRef.value?.load()
}
const afterAdd = refreshAll

const detailOpen = ref(false)
const detailId = ref(null)
function open(id) {
  detailId.value = id
  detailOpen.value = true
}
</script>

<template>
  <div class="page">
    <h1 class="page-title">{{ t('home.welcome', { name: auth.user?.full_name }) }}</h1>
    <!-- 未闭环警示：标红置顶 -->
    <el-card v-if="overdue.length" shadow="never" class="overdue">
      <template #header>
        <span class="od-title">⚠ {{ t('overdue.title') }} ({{ overdue.length }})</span>
      </template>
      <div class="od-list">
        <TaskCard v-for="task in overdue" :key="task.id" :task="task" @click="open(task.id)" />
      </div>
    </el-card>

    <div v-if="cards" class="cards">
      <el-card v-for="c in cards" :key="c.key" shadow="hover"
               :class="['shift-card', c.key, { mine: c.s.team_ids.includes(auth.user?.team_id) }]" @click="openDuty(c.key)">
        <div class="label">{{ t(`shift.${c.key}`) }}</div>
        <div class="teams">{{ mainTeam(c.s) }}</div>
        <div class="meta"><ShiftTag :kind="c.s.kind" /> {{ fmt(c.s.start) }} – {{ fmt(c.s.end) }}</div>
        <div v-if="c.d" class="counts">
          <span class="cnt">👷 {{ t('duty.onDuty', { n: c.d.counts.on_duty }) }}</span>
          <span class="cnt busy">{{ t('duty.busy', { n: c.d.counts.busy }) }}</span>
          <span class="cnt idle">{{ t('duty.idle', { n: c.d.counts.idle }) }}</span>
          <span v-if="c.d.counts.absent" class="cnt absent">{{ t('duty.absent', { n: c.d.counts.absent }) }}</span>
          <span v-if="c.d.counts.off_hours" class="cnt absent">{{ t('duty.offHours', { n: c.d.counts.off_hours }) }}</span>
          <span class="hint">{{ t('duty.clickHint') }} ›</span>
        </div>
      </el-card>
    </div>

    <el-collapse v-if="today" v-model="todayOpen" class="today">
      <el-collapse-item name="today">
        <template #title><b>{{ t('home.today') }} · {{ today.day }}</b></template>
        <div class="muted small">{{ t('home.todayHint') }}</div>
        <div class="today-grid">
          <button v-for="team in auth.teams" :key="team.id" type="button" @click="viewTeam(team.id)"
                  :class="['today-item', { mine: team.id === auth.user?.team_id, on: team.id === boardTeam }]">
            <span>{{ localName(team) }}</span>
            <ShiftTag :kind="today.shifts[team.id]" />
          </button>
        </div>
      </el-collapse-item>
    </el-collapse>

    <HandoverBoard ref="boardRef" :team-id="boardTeam" @changed="load" @reset="boardTeam = 0" />


    <DutyDrawer ref="drawerRef" v-model="dutyOpen" :which="dutyWhich" @add="quickAdd" @open-task="open"
                @loaded="(w, d) => (duty[w] = d)" />
    <TaskForm v-model="formOpen" :preset="preset" @saved="afterAdd" />
    <TaskDetail v-model="detailOpen" :task-id="detailId" @changed="refreshAll" />
  </div>
</template>

<style scoped>
.overdue { margin-bottom: 12px; border: 1px solid #f56c6c; }
.overdue :deep(.el-card__header) { background: #fef0f0; padding: 10px 16px; }
.od-title { color: #f56c6c; font-weight: 600; }
.od-list { display: flex; flex-direction: column; gap: 8px; max-height: 50vh; overflow: auto; }
.cards { display: grid; grid-template-columns: repeat(auto-fit, minmax(260px, 1fr)); gap: 12px; margin-bottom: 4px; }
.shift-card { cursor: pointer; }
.shift-card .label { color: #888; font-size: 13px; }
.shift-card .teams { font-size: 26px; font-weight: 600; margin: 6px 0; }
.shift-card .meta { color: #555; display: flex; gap: 8px; align-items: center; }
.shift-card.current { border-left: 4px solid #67c23a; }
.shift-card.next { border-left: 4px solid #409eff; }
.mine .teams, .today-item.mine span { color: #409eff; }
.counts { display: flex; gap: 10px; flex-wrap: wrap; align-items: center; margin-top: 10px; font-size: 13px; }
.cnt { color: #303133; }
.cnt.busy { color: #b88230; }
.cnt.idle { color: #529b2e; }
.cnt.absent { color: #909399; }
.hint { margin-left: auto; color: #409eff; font-size: 12px; }
.today { margin: 12px 0 4px; background: #fff; border-radius: 4px; padding: 0 16px; border: 1px solid var(--el-border-color-lighter); }
.today :deep(.el-collapse-item__header), .today :deep(.el-collapse-item__wrap) { border-bottom: 0; }
.muted { color: #909399; }
.small { font-size: 12px; margin-bottom: 8px; }
.today-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(150px, 1fr)); gap: 8px; }
.today-item { display: flex; justify-content: space-between; align-items: center; padding: 8px 10px; background: #f7f8fa; border-radius: 6px;
  border: 0; font: inherit; color: inherit; cursor: pointer; text-align: left; }
.today-item:hover, .today-item.on { background: #ecf5ff; }
.today-item.mine { outline: 1px solid #409eff; font-weight: 600; }
</style>
