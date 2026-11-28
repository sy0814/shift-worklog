<script setup>
// 首页的交接班：上一班移交过来的 + 本班待办 + 本班完成（不在班时显示上个班完成的），可多选一起移交
// 常白班上班的日子，常白班和当天白班的倒班班组合并成一块（两边班长都能操作）
// 看哪个班组由首页传进来（teamId，0 = 默认：有本班组的人看本班组，其他人看当前在班的）；
// 显示的不是「此刻在班」的班时，标题旁边写明是哪个班，免得看错
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRouter } from 'vue-router'
import api from '../api'
import { localName } from '../i18n'
import { useAuth } from '../stores/auth'
import { useOutbox } from '../stores/outbox'
import { warmTasks } from '../offline'
import ShiftTag from './ShiftTag.vue'
import TaskCard from './TaskCard.vue'
import TaskDetail from './TaskDetail.vue'
import HandoverDialog from './HandoverDialog.vue'

const { t, locale } = useI18n()
const auth = useAuth()
const outbox = useOutbox()
const router = useRouter()
const props = defineProps({ teamId: { type: Number, default: 0 } })
const teamId = computed(() => props.teamId)
const board = ref(null)
const noTeams = ref(false) // 车间里还没有班组（刚装好的系统）：显示怎么开始，不弹错误
const loading = ref(false)
const selected = ref([])

async function load() {
  loading.value = true
  try {
    if (!auth.teams.length) { noTeams.value = true; board.value = null; return } // 登录时已经取了班组列表
    let r
    try {
      r = await api.get('/board', { params: { team_id: teamId.value || undefined }, silent: true })
    } catch (e) {
      noTeams.value = e.response?.status === 404 && /^no teams/.test(e.response?.data?.detail || '')
      if (!noTeams.value) throw e
      board.value = null
      return
    }
    noTeams.value = false
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
const emit = defineEmits(['changed', 'reset'])
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
// 「小项目由当班自己添加」的项目（例如停送电）：本班每做一次就加一个小项目
const projName = (p) => p.name[locale.value] || p.name.zh || p.name.sr || p.name.en || ''
const itemOpen = ref(false)
const itemProj = ref(null)
const itemText = ref('')
const itemBusy = ref(false)
function openItem(p) { itemProj.value = p; itemText.value = ''; itemOpen.value = true }
async function saveItem() {
  itemBusy.value = true
  try {
    await api.post(`/projects/${itemProj.value.id}/subs`, { lang: locale.value, subs: [{ content: itemText.value.trim() }] })
    itemOpen.value = false
    load()
  } finally { itemBusy.value = false }
}

// 正在看的不是此刻在班的班（不在班 → 它的下一个班；或者从「今日排班」点了别的班组）：标题旁边写明
const viewing = computed(() => board.value && (props.teamId || !board.value.on_duty))
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
      <span v-if="viewing" class="viewing">
        {{ t('home.viewing') }}: <b>{{ board.team_ids.map(teamName).join(' + ') }}</b>
        <ShiftTag :kind="board.shift_kind" /> {{ board.shift_date.slice(5) }}<template v-if="!board.on_duty"> · {{ t('home.nextShiftTag') }}</template>
        <el-button v-if="teamId" link type="primary" @click="emit('reset')">{{ t('home.back') }}</el-button>
      </span>
    </div>

    <!-- 批量移交栏一直占位（没有可选的任务时变灰），切换班组时下面的列表不会上下跳 -->
    <div class="batch">
      <el-checkbox :model-value="allSelected" :indeterminate="selected.length > 0 && !allSelected" :disabled="!selectable.length" @change="toggleAll">{{ t('ho.selectAll') }}</el-checkbox>
      <span class="muted">{{ t('ho.selected', { n: selected.length }) }}</span>
      <el-button type="primary" size="small" :disabled="!selected.length" @click="hoOpen = true">{{ t('ho.batch') }}</el-button>
    </div>

    <el-empty v-if="noTeams" :description="t('board.noTeams')" :image-size="80">
      <el-button v-if="auth.isAdmin" type="primary" @click="router.push('/schedule?tab=teams')">{{ t('board.addTeams') }}</el-button>
    </el-empty>
    <div v-else v-loading="loading">
      <div v-if="board?.projects?.length" class="hb-projs">
        <div v-for="p in board.projects" :key="p.id" class="hb-proj">
          <span class="hb-pname">📁 {{ projName(p) }}</span>
          <span class="muted">{{ t('proj.boardHint', { n: p.total }) }}</span>
          <el-button v-if="p.can_add" size="small" type="primary" plain @click="openItem(p)">+ {{ t('proj.addItem') }}</el-button>
        </div>
      </div>
      <template v-for="sec in sections" :key="sec.key">
        <h3 class="sec">{{ sec.title }} <el-tag size="small" round>{{ sec.list.length }}</el-tag></h3>
        <div class="list">
          <div v-for="task in sec.list" :key="task.id" class="row">
            <!-- 每一行都有方框，卡片左边都对齐：能移交的可以勾；不能移交的（不可移交、没权限、已完成）是灰色方框 -->
            <span class="pick">
              <el-checkbox v-if="sec.selectable && task.perms?.handover" :model-value="selected.includes(task.id)" @change="(v) => toggle(task.id, v)" />
              <el-tooltip v-else-if="task.transferable === false && sec.selectable" :content="t('task.notTransferable')" placement="top">
                <el-checkbox disabled />
              </el-tooltip>
              <el-checkbox v-else disabled />
            </span>
            <TaskCard :task="task" class="grow" @click="open(task)" />
          </div>
          <div v-if="!sec.list.length" class="muted empty">{{ t('board.empty') }}</div>
        </div>
      </template>
    </div>

    <el-dialog v-model="itemOpen" :title="itemProj ? `${projName(itemProj)} · ${t('proj.addItem')}` : ''" width="min(480px, 94vw)" append-to-body>
      <el-input v-model="itemText" type="textarea" :autosize="{ minRows: 2, maxRows: 6 }" maxlength="5000" :placeholder="t('proj.itemPh')" />
      <template #footer>
        <el-button @click="itemOpen = false">{{ t('common.cancel') }}</el-button>
        <el-button type="primary" :loading="itemBusy" :disabled="!itemText.trim()" @click="saveItem">{{ t('common.save') }}</el-button>
      </template>
    </el-dialog>
    <TaskDetail v-model="detailOpen" :task-id="detailId" @changed="changed" />
    <HandoverDialog v-if="board" v-model="hoOpen" :task-ids="selected" :team-id="board.team_id" @done="() => { selected = []; changed() }" />
  </section>
</template>

<style scoped>
.hb { margin-top: 16px; }
.title { font-size: 17px; margin: 0; }
.viewing { display: inline-flex; align-items: center; gap: 6px; flex-wrap: wrap; color: #606266; font-size: 13px; }
.toolbar { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; margin-bottom: 8px; }
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
/* 不能勾的：明显的灰色方框 */
.pick :deep(.el-checkbox.is-disabled .el-checkbox__inner) { background: #dcdfe6; border-color: #c8cbd1; cursor: default; }

.grow { flex: 1; min-width: 0; }
.empty { padding: 4px 0 8px; }
.hb-projs { display: flex; flex-direction: column; gap: 6px; margin-top: 6px; }
.hb-proj { display: flex; gap: 10px; align-items: center; flex-wrap: wrap; background: #fff; border: 1px dashed #b3d8ff;
  border-radius: 6px; padding: 8px 12px; }
.hb-pname { font-weight: 600; }
</style>
