<script setup>
import { onMounted, onUnmounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import dayjs from 'dayjs'
import api from '../api'
import { localName } from '../i18n'
import { useAuth } from '../stores/auth'
import ShiftTag from '../components/ShiftTag.vue'
import TaskCard from '../components/TaskCard.vue'
import TaskDetail from '../components/TaskDetail.vue'

const { t } = useI18n()
const auth = useAuth()
const now = ref(null)
const overdue = ref([])
const detailOpen = ref(false)
const detailId = ref(null)
function open(task) {
  detailId.value = task.id
  detailOpen.value = true
}
const today = ref(null)

async function load() {
  overdue.value = (await api.get('/overdue')).data
  now.value = (await api.get('/shifts/now')).data
  const d = now.value.current.shift_date
  today.value = (await api.get('/shifts/calendar', { params: { start: d, end: d } })).data[0]
}

let timer
onMounted(() => {
  load()
  timer = setInterval(load, 60_000)
})
onUnmounted(() => clearInterval(timer))

const fmt = (s) => dayjs(s.slice(0, 16)).format('MM-DD HH:mm')
const teamNames = (ids) => ids.map((id) => localName(auth.teamById(id))).join(' + ')
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
        <TaskCard v-for="task in overdue" :key="task.id" :task="task" @click="open(task)" />
      </div>
    </el-card>

    <div v-if="now" class="cards">
      <el-card v-for="(s, key) in { current: now.current, next: now.next }" :key="key" shadow="never"
               :class="['shift-card', key, { mine: s.team_ids.includes(auth.user?.team_id) }]">
        <div class="label">{{ t(`shift.${key}`) }}</div>
        <div class="teams">{{ teamNames(s.team_ids) }}</div>
        <div class="meta"><ShiftTag :kind="s.kind" /> {{ fmt(s.start) }} – {{ fmt(s.end) }}</div>
      </el-card>
    </div>

    <el-card v-if="today" shadow="never" class="today">
      <template #header>{{ t('home.today') }} · {{ today.day }}</template>
      <div class="today-grid">
        <div v-for="team in auth.teams" :key="team.id" :class="['today-item', { mine: team.id === auth.user?.team_id }]">
          <span>{{ localName(team) }}</span>
          <ShiftTag :kind="today.shifts[team.id]" />
        </div>
      </div>
    </el-card>

    <div class="links">
      <router-link :to="{ name: 'board' }"><el-button type="primary" size="large">{{ t('nav2.board') }} →</el-button></router-link>
      <router-link :to="{ name: 'tasks' }"><el-button size="large">{{ t('nav2.tasks') }} →</el-button></router-link>
    </div>
    <TaskDetail v-model="detailOpen" :task-id="detailId" @changed="load" />
  </div>
</template>

<style scoped>
.overdue { margin-bottom: 12px; border: 1px solid #f56c6c; }
.overdue :deep(.el-card__header) { background: #fef0f0; padding: 10px 16px; }
.od-title { color: #f56c6c; font-weight: 600; }
.od-list { display: flex; flex-direction: column; gap: 8px; max-height: 50vh; overflow: auto; }
.links { display: flex; gap: 8px; flex-wrap: wrap; }
.cards { display: grid; grid-template-columns: repeat(auto-fit, minmax(260px, 1fr)); gap: 12px; margin-bottom: 12px; }
.shift-card .label { color: #888; font-size: 13px; }
.shift-card .teams { font-size: 26px; font-weight: 600; margin: 6px 0; }
.shift-card .meta { color: #555; display: flex; gap: 8px; align-items: center; }
.shift-card.current { border-left: 4px solid #67c23a; }
.shift-card.next { border-left: 4px solid #409eff; }
.mine .teams, .today-item.mine span { color: #409eff; }
.today { margin-bottom: 12px; }
.today-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(150px, 1fr)); gap: 8px; }
.today-item { display: flex; justify-content: space-between; align-items: center; padding: 8px 10px; background: #f7f8fa; border-radius: 6px; }
.today-item.mine { outline: 1px solid #409eff; font-weight: 600; }
</style>
