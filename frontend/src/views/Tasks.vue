<script setup>
import { onMounted, onUnmounted, reactive, ref, watch } from 'vue'
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
const filters = reactive({
  team_id: auth.user?.team_id ?? null,
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
    if (filters.team_id) params.append('team_id', filters.team_id)
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
watch(() => [filters.team_id, filters.statusSet, filters.dates], () => load())
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
      <el-select v-model="filters.team_id" clearable :placeholder="t('task.allTeams')" style="width: 130px">
        <el-option v-for="tm in auth.teams" :key="tm.id" :label="localName(tm)" :value="tm.id" />
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
