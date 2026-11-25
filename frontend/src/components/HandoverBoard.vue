<script setup>
// 首页的交接班：上一班移交过来的 + 本班待办 + 本班完成（不在班时显示上个班完成的），可多选一起移交
// 常白班上班的日子，常白班和当天白班的倒班班组合并成一块（两边班长都能操作）
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import api from '../api'
import { localName } from '../i18n'
import { useAuth } from '../stores/auth'
import { useOutbox } from '../stores/outbox'
import { warmTasks } from '../offline'
import ShiftTag from './ShiftTag.vue'
import TaskCard from './TaskCard.vue'
import TaskDetail from './TaskDetail.vue'
import HandoverDialog from './HandoverDialog.vue'

const { t } = useI18n()
const auth = useAuth()
const outbox = useOutbox()
const teamId = ref(0) // 0 = 默认（管理员：当前在班班组；班长：本班组）
const board = ref(null)
const loading = ref(false)
const selected = ref([])

async function load() {
  loading.value = true
  try {
    const r = await api.get('/board', { params: { team_id: teamId.value || undefined } })
    board.value = r.data
    if (!r.headers['x-from-cache']) { // 联网时顺便缓存任务详情，离线也能打开
      const ids = [...board.value.received, ...board.value.todo].filter((x) => ['not_started', 'in_progress'].includes(x.status)).map((x) => x.id)
      setTimeout(() => warmTasks(api, ids), 1500)
    }
    const openIds = new Set(openTasks.value.filter((x) => x.perms?.handover).map((x) => x.id))
    selected.value = selected.value.filter((id) => openIds.has(id))
    watchTranslations([...board.value.received, ...board.value.todo, ...board.value.done_recent])
  } finally {
    loading.value = false
  }
}
watch(teamId, () => { selected.value = []; load() })
watch(() => outbox.lastSyncedTaskIds.length, () => load()) // 离线草稿 / 状态同步上去了
onMounted(load)
defineExpose({ load })
const emit = defineEmits(['changed'])
function changed() { // 任务有变化：自己刷新，并通知首页刷新在岗人数
  load()
  emit('changed')
}

// 有任务还在后台翻译时，每 4 秒刷新一次（最多 1 分钟）
let trTimer = null
let trTries = 0
function watchTranslations(list) {
  clearTimeout(trTimer)
  if (!list.some((x) => x.translation_status === 'pending')) { trTries = 0; return }
  if (trTries++ >= 15) return
  trTimer = setTimeout(() => load(), 4000)
}
onUnmounted(() => clearTimeout(trTimer))

const openTasks = computed(() => (board.value ? [...board.value.received, ...board.value.todo] : []))
const selectable = computed(() => openTasks.value.filter((x) => x.perms?.handover))
const allSelected = computed(() => selectable.value.length > 0 && selected.value.length === selectable.value.length)
function toggleAll(v) {
  selected.value = v ? selectable.value.map((x) => x.id) : []
}
function toggle(id, v) {
  selected.value = v ? [...selected.value, id] : selected.value.filter((x) => x !== id)
}

const detailOpen = ref(false)
const detailId = ref(null)
function open(task) {
  detailId.value = task.id
  detailOpen.value = true
}
const hoOpen = ref(false)
const teamName = (id) => localName(auth.teamById(id))
// 班组切换：只列倒班班组 + 常白班（合并在服务器端处理）
const switchTeams = computed(() => auth.teams)
const sections = computed(() => board.value && [
  { key: 'received', title: t('board.received'), list: board.value.received, selectable: true },
  { key: 'todo', title: t('board.todo'), list: board.value.todo, selectable: true },
  { key: 'done', list: board.value.done_recent,
    title: board.value.on_duty ? t('board.doneRecent')
      : t('board.doneLast', { date: board.value.done_shift_date.slice(5), shift: t(`shift.${board.value.done_shift_kind}`) }) },
])
</script>

<template>
  <section class="hb">
    <div class="toolbar">
      <h2 class="title">{{ t('nav2.board') }}</h2>
      <el-radio-group v-model="teamId" size="small">
        <el-radio-button :value="0">{{ auth.hasOwnTeamHere ? t('home.myTeam') : t('shift.current') }}</el-radio-button>
        <el-radio-button v-for="tm in switchTeams" :key="tm.id" :value="tm.id">{{ localName(tm) }}</el-radio-button>
      </el-radio-group>
    </div>

    <el-card v-if="board" shadow="never" class="head">
      <div class="head-row">
        <b class="big">{{ board.team_ids.map(teamName).join(' + ') }}</b>
        <ShiftTag :kind="board.shift_kind" />
        <span>{{ board.on_duty ? t('board.onDuty', { shift: board.shift_date.slice(5) }) : t('board.next', { date: board.shift_date.slice(5), shift: '' }) }}</span>
      </div>
      <div class="head-row muted">
        <span v-if="board.prev_team_ids.length">{{ t('board.prev') }}: {{ board.prev_team_ids.map(teamName).join(' + ') }}</span>
        <span v-if="board.next_team_id">{{ t('board.nextTeam') }}: {{ teamName(board.next_team_id) }}</span>
      </div>
    </el-card>

    <!-- 批量移交栏一直占位（没有可选的任务时变灰），切换班组时下面的列表不会上下跳 -->
    <div class="batch">
      <el-checkbox :model-value="allSelected" :indeterminate="selected.length > 0 && !allSelected" :disabled="!selectable.length" @change="toggleAll">{{ t('ho.selectAll') }}</el-checkbox>
      <span class="muted">{{ t('ho.selected', { n: selected.length }) }}</span>
      <el-button type="primary" size="small" :disabled="!selected.length" @click="hoOpen = true">{{ t('ho.batch') }}</el-button>
    </div>

    <div v-loading="loading">
      <template v-for="sec in sections" :key="sec.key">
        <h3 class="sec">{{ sec.title }} <el-tag size="small" round>{{ sec.list.length }}</el-tag></h3>
        <div class="list">
          <div v-for="task in sec.list" :key="task.id" class="row">
            <!-- 能移交的放勾选框；不能移交的留同样宽的位置（不可移交的显示 🔒），卡片左边都对齐 -->
            <span v-if="sec.selectable" class="pick">
              <el-checkbox v-if="task.perms?.handover" :model-value="selected.includes(task.id)" @change="(v) => toggle(task.id, v)" />
              <el-tooltip v-else-if="task.transferable === false" :content="t('task.notTransferable')" placement="top">
                <span class="lock">🔒</span>
              </el-tooltip>
            </span>
            <TaskCard :task="task" class="grow" @click="open(task)" />
          </div>
          <div v-if="!sec.list.length" class="muted empty">{{ t('board.empty') }}</div>
        </div>
      </template>
    </div>

    <TaskDetail v-model="detailOpen" :task-id="detailId" @changed="changed" />
    <HandoverDialog v-if="board" v-model="hoOpen" :task-ids="selected" :team-id="board.team_id" @done="() => { selected = []; changed() }" />
  </section>
</template>

<style scoped>
.hb { margin-top: 16px; }
.title { font-size: 17px; margin: 0; flex: 1; }
.toolbar { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; margin-bottom: 8px; }
.toolbar :deep(.el-radio-group) { flex-wrap: wrap; }
.head { margin-bottom: 8px; }
.head-row { display: flex; gap: 10px; align-items: center; flex-wrap: wrap; }
.head-row + .head-row { margin-top: 6px; }
.big { font-size: 18px; }
.muted { color: #909399; font-size: 13px; }
.batch { position: sticky; top: 52px; z-index: 5; display: flex; gap: 12px; align-items: center; background: #f4f5f7; padding: 8px 0; }
.sec { margin: 14px 0 8px; font-size: 15px; display: flex; align-items: center; gap: 6px; }
.list { display: flex; flex-direction: column; gap: 8px; }
.row { display: flex; gap: 8px; align-items: flex-start; }
.pick { flex: 0 0 18px; display: flex; justify-content: center; margin-top: 10px; height: 20px; }
.pick :deep(.el-checkbox) { height: 20px; margin: 0; }
.lock { font-size: 12px; line-height: 20px; opacity: .55; cursor: default; }
.grow { flex: 1; min-width: 0; }
.empty { padding: 4px 0 8px; }
</style>
