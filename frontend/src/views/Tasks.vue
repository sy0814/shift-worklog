<script setup>
import { computed, onMounted, onUnmounted, reactive, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { Plus } from '@element-plus/icons-vue'
import api from '../api'
import { warmTasks } from '../offline'
import { localName } from '../i18n'
import { useAuth } from '../stores/auth'
import { useOutbox } from '../stores/outbox'
import TaskCard from '../components/TaskCard.vue'
import TaskDetail from '../components/TaskDetail.vue'
import TaskForm from '../components/TaskForm.vue'
import ExportDialog from '../components/ExportDialog.vue'

const { t } = useI18n()
const auth = useAuth()
const outbox = useOutbox()

const STATUS_SETS = { open: ['not_started', 'in_progress'], done: ['done'], all: [] }
// 「我的任务 / 班组任务」（名册里的人才有）：成员（不能改班组任务的人）默认看自己的，班长等默认看班组的
const hasMine = !!auth.user?.worker_id
// 班组下拉只列能看的班组（和后端 visible_team_ids 一致）：「看任务」本车间 / 全厂 = 当前车间所有班组；
// 本班组 = 自己的班组 + 当天合并显示的班组。选了看不到的班组只会是空列表，容易以为坏了
const visibleTeams = computed(() => {
  if (auth.isAdmin || ['dept', 'all'].includes(auth.scope('task.view'))) return auth.teams
  const ids = new Set([...(auth.user?.group_team_ids || []), auth.user?.team_id])
  return auth.teams.filter((t) => ids.has(t.id))
})
const filters = reactive({
  scope: hasMine && ['none', 'self'].includes(auth.scope('task.edit')) ? 'mine' : 'team',
  team_id: auth.user?.team_id ?? null,
  worker_id: null, // 人员筛选：这个人是带队人或参与人员的任务
  statusSet: 'open',
  dates: null,
  q: '',
})
const items = ref([])
const total = ref(0)
const loading = ref(false)
const PAGE = 30

async function load(append = false) {
  loading.value = true
  try {
    const params = new URLSearchParams()
    if (filters.scope === 'mine') params.append('worker_id', auth.user.worker_id) // 自己是带队人或参与人员的（不限班组）
    else {
      if (filters.team_id) params.append('team_id', filters.team_id)
      if (filters.worker_id) params.append('worker_id', filters.worker_id)
    }
    for (const s of STATUS_SETS[filters.statusSet]) params.append('status', s)
    if (filters.dates) {
      params.append('date_from', filters.dates[0])
      params.append('date_to', filters.dates[1])
    }
    if (filters.q.trim()) params.append('q', filters.q.trim())
    params.append('limit', PAGE)
    params.append('offset', append ? items.value.length : 0)
    const { data, headers } = await api.get('/tasks', { params })
    if (!headers['x-from-cache']) { // 联网时缓存未完成任务的详情，离线也能打开
      const ids = data.items.filter((x) => ['not_started', 'in_progress'].includes(x.status)).map((x) => x.id)
      setTimeout(() => warmTasks(api, ids), 2000)
    }
    items.value = append ? [...items.value, ...data.items] : data.items
    total.value = data.total
    watchTranslations(items.value)
  } finally {
    loading.value = false
  }
}
watch(() => [filters.scope, filters.team_id, filters.worker_id, filters.statusSet, filters.dates], () => load())
// 选了人就不限班组（他顶过别的班组的班，任务也要能列出来）
watch(() => filters.worker_id, (v) => { if (v) filters.team_id = null })

// 人员筛选的选项：能看的班组里的人（看任务范围本车间 / 全厂的，再加上本车间没有班组的人，例如管理人员），按班组分组
const people = ref([])
api.get('/workers', { silent: true }).then((r) => { people.value = r.data }).catch(() => {})
const peopleGroups = computed(() => {
  const wide = auth.isAdmin || ['dept', 'all'].includes(auth.scope('task.view'))
  const groups = visibleTeams.value.map((tm) => ({ label: localName(tm), list: people.value.filter((w) => w.team_id === tm.id) }))
  if (wide) groups.push({ label: t('task.noTeam'), list: people.value.filter((w) => !w.team_id && (!auth.dept || w.department_id === auth.dept)) })
  return groups.filter((g) => g.list.length)
})
// 离线草稿同步成功后刷新列表
watch(() => outbox.lastSyncedTaskIds.length, () => load())
onMounted(load)

// 有任务还在后台翻译时，每 4 秒刷新一次（最多 1 分钟），翻译好后列表自动显示译文
let trTimer = null
let trTries = 0
function watchTranslations(list) {
  clearTimeout(trTimer)
  if (!list.some((x) => x.translation_status === 'pending')) { trTries = 0; return }
  if (trTries++ >= 15) return
  trTimer = setTimeout(() => load(), 4000)
}
onUnmounted(() => clearTimeout(trTimer))

const formOpen = ref(false)
const exportOpen = ref(false)
const detailOpen = ref(false)
const detailId = ref(null)
function open(task) {
  detailId.value = task.id
  detailOpen.value = true
}
</script>

<template>
  <div class="page">
    <div class="toolbar">
      <el-radio-group v-if="hasMine" v-model="filters.scope">
        <el-radio-button value="mine">{{ t('task.scopeMine') }}</el-radio-button>
        <el-radio-button value="team">{{ t('task.scopeTeam') }}</el-radio-button>
      </el-radio-group>
      <el-select v-if="filters.scope === 'team'" v-model="filters.team_id" clearable :placeholder="t('task.allTeams')" style="width: 130px">
        <el-option v-for="tm in visibleTeams" :key="tm.id" :label="localName(tm)" :value="tm.id" />
      </el-select>
      <el-select v-if="filters.scope === 'team'" v-model="filters.worker_id" filterable clearable :placeholder="t('task.person')" style="width: 150px">
        <el-option-group v-for="g in peopleGroups" :key="g.label" :label="g.label">
          <el-option v-for="w in g.list" :key="w.id" :label="w.name" :value="w.id" />
        </el-option-group>
      </el-select>
      <el-radio-group v-model="filters.statusSet">
        <el-radio-button value="open">{{ t('status.open') }}</el-radio-button>
        <el-radio-button value="done">{{ t('status.done') }}</el-radio-button>
        <el-radio-button value="all">{{ t('status.all') }}</el-radio-button>
      </el-radio-group>
      <el-date-picker v-model="filters.dates" type="daterange" value-format="YYYY-MM-DD" unlink-panels
                      :start-placeholder="t('task.dateRange')" :end-placeholder="t('task.dateRange')" style="max-width: 260px" />
      <el-input v-model="filters.q" :placeholder="t('task.search')" clearable style="width: 180px"
                @keyup.enter="load()" @clear="load()" />
      <span class="spacer" />
      <el-button v-if="auth.can('export')" @click="exportOpen = true">{{ t('exp.title') }}</el-button>
      <el-button v-if="auth.can('task.create')" class="new-btn" type="primary" :icon="Plus" @click="formOpen = true">{{ t('task.new') }}</el-button>
    </div>

    <div v-loading="loading" class="list">
      <TaskCard v-for="task in items" :key="task.id" :task="task" @click="open(task)" />
      <el-empty v-if="!loading && !items.length" :description="t('task.empty')" />
      <el-button v-if="items.length < total" class="more" text @click="load(true)">{{ t('task.loadMore') }} ({{ items.length }}/{{ total }})</el-button>
    </div>

    <el-button v-if="auth.can('task.create')" class="fab" type="primary" circle :icon="Plus" size="large" @click="formOpen = true" />
    <TaskForm v-model="formOpen" @saved="load()" />
    <ExportDialog v-model="exportOpen" :team-id="filters.team_id" />
    <TaskDetail v-model="detailOpen" :task-id="detailId" @changed="load()" />
  </div>
</template>

<style scoped>
.spacer { flex: 1; }
.list { display: flex; flex-direction: column; gap: 8px; min-height: 120px; }
.more { align-self: center; }
.fab { display: none; position: fixed; right: 20px; bottom: calc(76px + env(safe-area-inset-bottom)); width: 56px; height: 56px; font-size: 24px; box-shadow: 0 4px 12px rgba(0,0,0,.25); z-index: 10; }
@media (max-width: 640px) {
  .fab { display: inline-flex; }
  .new-btn { display: none; }
}
</style>
