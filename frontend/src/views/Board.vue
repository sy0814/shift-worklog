<script setup>
// 交接班 / 早班会视图：上一班移交过来的 + 本班待办，可多选一起移交
import { computed, onMounted, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import api from '../api'
import { localName } from '../i18n'
import { useAuth } from '../stores/auth'
import ShiftTag from '../components/ShiftTag.vue'
import TaskCard from '../components/TaskCard.vue'
import TaskDetail from '../components/TaskDetail.vue'
import HandoverDialog from '../components/HandoverDialog.vue'

const { t } = useI18n()
const auth = useAuth()
const teamId = ref(auth.user?.team_id ?? auth.teams[0]?.id)
const board = ref(null)
const loading = ref(false)
const selected = ref([])

async function load() {
  loading.value = true
  try {
    board.value = (await api.get('/board', { params: { team_id: teamId.value } })).data
    const openIds = new Set([...board.value.received, ...board.value.todo].map((x) => x.id))
    selected.value = selected.value.filter((id) => openIds.has(id))
  } finally {
    loading.value = false
  }
}
watch(teamId, () => { selected.value = []; load() })
onMounted(load)

const canEdit = computed(() => auth.isAdmin || auth.user?.team_id === teamId.value)
const openTasks = computed(() => (board.value ? [...board.value.received, ...board.value.todo] : []))
const allSelected = computed(() => openTasks.value.length > 0 && selected.value.length === openTasks.value.length)
function toggleAll(v) {
  selected.value = v ? openTasks.value.map((x) => x.id) : []
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
const sections = computed(() => board.value && [
  { key: 'received', title: t('board.received'), list: board.value.received, selectable: true },
  { key: 'todo', title: t('board.todo'), list: board.value.todo, selectable: true },
  { key: 'done', title: t('board.doneRecent'), list: board.value.done_recent },
  { key: 'out', title: t('board.outRecent'), list: board.value.handed_out_recent },
])
</script>

<template>
  <div class="page">
    <div class="toolbar">
      <el-radio-group v-model="teamId">
        <el-radio-button v-for="tm in auth.teams" :key="tm.id" :value="tm.id">{{ localName(tm) }}</el-radio-button>
      </el-radio-group>
    </div>

    <el-card v-if="board" shadow="never" class="head">
      <div class="head-row">
        <b class="big">{{ teamName(board.team_id) }}</b>
        <ShiftTag :kind="board.shift_kind" />
        <span>{{ board.on_duty ? t('board.onDuty', { shift: board.shift_date.slice(5) }) : t('board.next', { date: board.shift_date.slice(5), shift: '' }) }}</span>
      </div>
      <div class="head-row muted">
        <span v-if="board.prev_team_ids.length">{{ t('board.prev') }}: {{ board.prev_team_ids.map(teamName).join(' + ') }}</span>
        <span v-if="board.next_team_id">{{ t('board.nextTeam') }}: {{ teamName(board.next_team_id) }}</span>
      </div>
    </el-card>

    <div v-if="canEdit && openTasks.length" class="batch">
      <el-checkbox :model-value="allSelected" :indeterminate="selected.length > 0 && !allSelected" @change="toggleAll">{{ t('ho.selectAll') }}</el-checkbox>
      <span class="muted">{{ t('ho.selected', { n: selected.length }) }}</span>
      <el-button type="primary" :disabled="!selected.length" @click="hoOpen = true">{{ t('ho.batch') }}</el-button>
    </div>

    <div v-loading="loading">
      <template v-for="sec in sections" :key="sec.key">
        <h3 class="sec">{{ sec.title }} <el-tag size="small" round>{{ sec.list.length }}</el-tag></h3>
        <div class="list">
          <div v-for="task in sec.list" :key="task.id" class="row">
            <el-checkbox v-if="sec.selectable && canEdit" :model-value="selected.includes(task.id)" class="pick"
                         @change="(v) => toggle(task.id, v)" />
            <TaskCard :task="task" class="grow" @click="open(task)" />
          </div>
          <div v-if="!sec.list.length" class="muted empty">{{ t('board.empty') }}</div>
        </div>
      </template>
    </div>

    <TaskDetail v-model="detailOpen" :task-id="detailId" @changed="load" />
    <HandoverDialog v-model="hoOpen" :task-ids="selected" :team-id="teamId" @done="() => { selected = []; load() }" />
  </div>
</template>

<style scoped>
.head { margin-bottom: 12px; }
.head-row { display: flex; gap: 10px; align-items: center; flex-wrap: wrap; }
.head-row + .head-row { margin-top: 6px; }
.big { font-size: 20px; }
.muted { color: #909399; font-size: 13px; }
.batch { position: sticky; top: 0; z-index: 5; display: flex; gap: 12px; align-items: center; background: #f4f5f7; padding: 8px 0; }
.sec { margin: 16px 0 8px; font-size: 15px; display: flex; align-items: center; gap: 6px; }
.list { display: flex; flex-direction: column; gap: 8px; }
.row { display: flex; gap: 8px; align-items: flex-start; }
.pick { margin-top: 10px; }
.grow { flex: 1; min-width: 0; }
.empty { padding: 4px 0 8px; }
</style>
