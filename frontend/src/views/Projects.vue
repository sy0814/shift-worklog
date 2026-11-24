<script setup>
// 项目：一个项目下面多个子项目（子项目就是普通任务，出现在对应班组的交接班里）。
// 子项目分给班组（班长再安排人）或具体的人；可移交的项目，子项目本班没做完下班后自动交给下一班；全部完成（或废弃）才算完成。
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { ElMessage } from 'element-plus'
import { Plus } from '@element-plus/icons-vue'
import dayjs from 'dayjs'
import api from '../api'
import { localName, localText } from '../i18n'
import { isNarrow } from '../format'
import { useAuth } from '../stores/auth'
import TaskCard from '../components/TaskCard.vue'
import TaskDetail from '../components/TaskDetail.vue'
import TargetPicker from '../components/TargetPicker.vue'
import Inspections from './Inspections.vue'
import { useRoute, useRouter } from 'vue-router'

const { t, locale } = useI18n()
const auth = useAuth()
// 两个标签：项目 / 定期巡查（定期巡查有小项目时，每次派发生成一个项目）
const route = useRoute()
const router = useRouter()
const tab = ref(route.query.tab === 'inspections' ? 'inspections' : 'projects')
watch(tab, (v) => router.replace({ query: v === 'inspections' ? { tab: v } : {} }))
const state = ref('open')
const rows = ref([])
const loading = ref(false)
async function load() {
  loading.value = true
  try {
    rows.value = (await api.get('/projects', { params: { state: state.value } })).data
  } finally {
    loading.value = false
  }
}
watch(state, load)
onMounted(load)

// 选人用：员工名单 + 每个人下一个班
const workers = ref([])
const slots = ref({})
async function loadPeople() {
  if (workers.value.length) return
  const [w, p] = await Promise.all([api.get('/workers'), api.get('/projects/people')])
  workers.value = w.data
  slots.value = Object.fromEntries(p.data.map((x) => [x.worker_id, x]))
}

const name = (p) => localText(p.name, p.source_lang).text
const pct = (p) => (p.total ? Math.round(((p.done + p.discarded) / p.total) * 100) : 0)
const overdue = (p) => !p.closed_at && p.deadline && p.deadline < dayjs().format('YYYY-MM-DD')

// ---------------- 新建 ----------------
const formOpen = ref(false)
const form = reactive({})
const blankSub = () => ({ content: '', target: { mode: 'team', team_id: auth.user?.team_id ?? null, worker_id: null } })
function openCreate() {
  Object.assign(form, { name: '', transferable: true, deadline: null, team_id: auth.user?.team_id ?? auth.teams[0]?.id, subs: [blankSub()] })
  loadPeople()
  formOpen.value = true
}
const subBody = (s) => ({ content: s.content.trim(), ...(s.target.mode === 'team' ? { team_id: s.target.team_id } : { worker_id: s.target.worker_id }) })
const subOk = (s) => s.content.trim() && (s.target.mode === 'team' ? s.target.team_id : s.target.worker_id)
const formOk = computed(() => form.name?.trim() && form.subs?.length && form.subs.every(subOk))
async function create() {
  const body = { name: form.name.trim(), lang: locale.value, transferable: form.transferable, deadline: form.deadline || null,
    subs: form.subs.map(subBody), ...(auth.scope('project.manage') === 'all' ? { team_id: form.team_id } : {}) }
  const p = (await api.post('/projects', body)).data
  formOpen.value = false
  ElMessage.success(t('common.saved'))
  await load()
  openDetail(p.id)
}

// ---------------- 详情 ----------------
const detailOpen = ref(false)
const detail = ref(null)
async function openDetail(id) {
  detail.value = (await api.get(`/projects/${id}`)).data
  detailOpen.value = true
  loadPeople()
}
async function reloadDetail() {
  if (detail.value) detail.value = (await api.get(`/projects/${detail.value.id}`)).data
  load()
}
async function setTransferable(v) {
  detail.value = (await api.patch(`/projects/${detail.value.id}`, { transferable: v })).data
  load()
}
// 加子项目
const addOpen = ref(false)
const adding = ref([])
function openAdd() { adding.value = [blankSub()]; addOpen.value = true }
async function saveAdd() {
  detail.value = (await api.post(`/projects/${detail.value.id}/subs`, { lang: locale.value, subs: adding.value.map(subBody) })).data
  addOpen.value = false
  load()
}
// 改派
const asOpen = ref(false)
const asTask = ref(null)
const asTarget = reactive({ mode: 'person', team_id: null, worker_id: null })
function openAssign(task) {
  asTask.value = task
  Object.assign(asTarget, { mode: task.lead ? 'person' : 'team', team_id: task.team_id, worker_id: task.lead?.id ?? null })
  asOpen.value = true
}
async function saveAssign() {
  await api.post(`/projects/${detail.value.id}/subs/${asTask.value.id}/assign`,
    asTarget.mode === 'team' ? { team_id: asTarget.team_id } : { worker_id: asTarget.worker_id })
  asOpen.value = false
  ElMessage.success(t('common.saved'))
  reloadDetail()
}
const taskOpen = ref(false)
const taskId = ref(null)
function openTask(task) { taskId.value = task.id; taskOpen.value = true }
const open = (s) => ['not_started', 'in_progress'].includes(s.status)
</script>

<template>
  <div class="page">
    <el-tabs v-model="tab">
      <el-tab-pane :label="t('proj.title')" name="projects" />
      <el-tab-pane :label="t('insp.title')" name="inspections" lazy />
    </el-tabs>
    <Inspections v-if="tab === 'inspections'" embedded @open-project="openDetail" />
    <template v-else>
    <div class="toolbar">
      <span style="flex: 1" />
      <el-radio-group v-model="state" size="small">
        <el-radio-button value="open">{{ t('proj.open') }}</el-radio-button>
        <el-radio-button value="closed">{{ t('proj.closed') }}</el-radio-button>
        <el-radio-button value="all">{{ t('proj.all') }}</el-radio-button>
      </el-radio-group>
      <el-button v-if="auth.can('project.manage')" type="primary" :icon="Plus" @click="openCreate">{{ t('proj.add') }}</el-button>
    </div>
    <p class="muted small">{{ t('proj.hint') }}</p>

    <div v-loading="loading" class="list">
      <div v-if="!rows.length && !loading" class="muted">{{ t('proj.none') }}</div>
      <div v-for="p in rows" :key="p.id" :class="['pcard', { done: p.closed_at, late: overdue(p) }]" @click="openDetail(p.id)">
        <div class="ptop">
          <b class="pname">{{ name(p) }}</b>
          <el-tag size="small" effect="plain">{{ localName(auth.teamById(p.team_id)) }}</el-tag>
          <el-tag v-if="!p.transferable" size="small" type="info">{{ t('proj.fixed') }}</el-tag>
          <el-tag v-if="p.closed_at" size="small" type="success">{{ t('proj.closedTag') }}</el-tag>
          <el-tag v-else-if="overdue(p)" size="small" type="danger">{{ t('proj.late') }}</el-tag>
          <span class="muted small grow" />
          <span v-if="p.deadline" class="muted small">{{ t('proj.deadline') }} {{ p.deadline }}</span>
        </div>
        <el-progress :percentage="pct(p)" :status="p.closed_at ? 'success' : undefined" :stroke-width="10" />
        <div class="muted small">{{ t('proj.counts', { done: p.done, total: p.total, open: p.open }) }}<template v-if="p.discarded"> · {{ t('proj.discarded', { n: p.discarded }) }}</template> · {{ p.created_by_name }}</div>
      </div>
    </div>
    </template>

    <!-- 新建项目 -->
    <el-dialog v-model="formOpen" :title="t('proj.add')" width="min(760px, 96vw)" :fullscreen="isNarrow()" append-to-body :close-on-click-modal="false">
      <el-form label-width="auto">
        <el-form-item :label="t('proj.name')"><el-input v-model="form.name" maxlength="200" /></el-form-item>
        <el-form-item v-if="auth.scope('project.manage') === 'all'" :label="t('proj.team')">
          <el-select v-model="form.team_id" style="width: 160px"><el-option v-for="tm in auth.teams" :key="tm.id" :label="localName(tm)" :value="tm.id" /></el-select>
        </el-form-item>
        <el-form-item :label="t('proj.transferable')">
          <div class="col">
            <el-switch v-model="form.transferable" />
            <small class="muted">{{ form.transferable ? t('proj.transferableHint') : t('proj.fixedHint') }}</small>
          </div>
        </el-form-item>
        <el-form-item :label="t('proj.deadline')"><el-date-picker v-model="form.deadline" value-format="YYYY-MM-DD" /></el-form-item>
        <el-form-item :label="t('proj.subs')">
          <div class="subs">
            <div v-for="(s, i) in form.subs" :key="i" class="sub">
              <span class="no">{{ i + 1 }}</span>
              <div class="grow">
                <el-input v-model="s.content" type="textarea" :autosize="{ minRows: 1, maxRows: 4 }" :placeholder="t('proj.subPh')" maxlength="5000" />
                <TargetPicker v-model="s.target" :workers="workers" :slots="slots" class="mt4" />
              </div>
              <el-button v-if="form.subs.length > 1" link type="danger" @click="form.subs.splice(i, 1)">✕</el-button>
            </div>
            <el-button size="small" :icon="Plus" @click="form.subs.push(blankSub())">{{ t('proj.addSub') }}</el-button>
          </div>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="formOpen = false">{{ t('common.cancel') }}</el-button>
        <el-button type="primary" :disabled="!formOk" @click="create">{{ t('common.save') }}</el-button>
      </template>
    </el-dialog>

    <!-- 项目详情 -->
    <el-drawer v-model="detailOpen" :size="isNarrow() ? '100%' : '640px'" :title="detail ? name(detail) : ''" append-to-body>
      <template v-if="detail">
        <div class="dhead">
          <el-progress :percentage="pct(detail)" :status="detail.closed_at ? 'success' : undefined" :stroke-width="12" />
          <div class="muted small">{{ t('proj.counts', { done: detail.done, total: detail.total, open: detail.open }) }}<template v-if="detail.discarded"> · {{ t('proj.discarded', { n: detail.discarded }) }}</template></div>
          <div class="row">
            <el-tag effect="plain">{{ localName(auth.teamById(detail.team_id)) }}</el-tag>
            <span v-if="detail.deadline" :class="{ red: overdue(detail) }">{{ t('proj.deadline') }} {{ detail.deadline }}</span>
            <el-tag v-if="detail.closed_at" type="success">{{ t('proj.closedTag') }} {{ dayjs(detail.closed_at).format('MM-DD HH:mm') }}</el-tag>
          </div>
          <div class="row">
            <el-switch :model-value="detail.transferable" :disabled="!detail.can_manage" @change="setTransferable" />
            <span>{{ detail.transferable ? t('proj.transferableHint') : t('proj.fixedHint') }}</span>
          </div>
          <div v-if="detail.name.zh || detail.name.sr || detail.name.en" class="muted small">
            <template v-for="l in ['zh', 'sr', 'en'].filter((x) => x !== locale && detail.name[x])" :key="l">{{ l.toUpperCase() }}: {{ detail.name[l] }}　</template>
          </div>
        </div>
        <div class="subhead">
          <h4>{{ t('proj.subs') }}</h4>
          <el-button v-if="detail.can_manage" size="small" :icon="Plus" @click="openAdd">{{ t('proj.addSub') }}</el-button>
        </div>
        <div v-for="s in detail.subs" :key="s.id" class="drow">
          <TaskCard :task="s" class="grow" @click="openTask(s)" />
          <el-button v-if="detail.can_manage && open(s)" size="small" link type="primary" @click="openAssign(s)">{{ t('proj.reassign') }}</el-button>
        </div>
      </template>
    </el-drawer>

    <el-dialog v-model="addOpen" :title="t('proj.addSub')" width="min(640px, 96vw)" append-to-body>
      <div class="subs">
        <div v-for="(s, i) in adding" :key="i" class="sub">
          <span class="no">{{ i + 1 }}</span>
          <div class="grow">
            <el-input v-model="s.content" type="textarea" :autosize="{ minRows: 1, maxRows: 4 }" :placeholder="t('proj.subPh')" />
            <TargetPicker v-model="s.target" :workers="workers" :slots="slots" class="mt4" />
          </div>
          <el-button v-if="adding.length > 1" link type="danger" @click="adding.splice(i, 1)">✕</el-button>
        </div>
        <el-button size="small" :icon="Plus" @click="adding.push(blankSub())">{{ t('proj.addSub') }}</el-button>
      </div>
      <template #footer>
        <el-button @click="addOpen = false">{{ t('common.cancel') }}</el-button>
        <el-button type="primary" :disabled="!adding.every(subOk)" @click="saveAdd">{{ t('common.save') }}</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="asOpen" :title="t('proj.reassign')" width="min(480px, 94vw)" append-to-body>
      <p v-if="asTask" class="muted small">{{ localText(asTask.content, asTask.source_lang).text }}</p>
      <TargetPicker v-model="asTarget" :workers="workers" :slots="slots" />
      <p class="muted small">{{ t('proj.reassignHint') }}</p>
      <template #footer>
        <el-button @click="asOpen = false">{{ t('common.cancel') }}</el-button>
        <el-button type="primary" :disabled="asTarget.mode === 'team' ? !asTarget.team_id : !asTarget.worker_id" @click="saveAssign">{{ t('common.save') }}</el-button>
      </template>
    </el-dialog>

    <TaskDetail v-model="taskOpen" :task-id="taskId" @changed="reloadDetail" />
  </div>
</template>

<style scoped>
.toolbar { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }
.muted { color: #909399; }
.small { font-size: 12px; }
.grow { flex: 1; min-width: 0; }
.list { display: flex; flex-direction: column; gap: 10px; min-height: 80px; }
.pcard { background: #fff; border-radius: 8px; padding: 12px 14px; cursor: pointer; border-left: 4px solid #409eff; display: flex; flex-direction: column; gap: 6px; }
.pcard.done { border-left-color: #67c23a; opacity: .85; }
.pcard.late { border-left-color: #f56c6c; }
.pcard:hover .pname { color: #409eff; }
.ptop { display: flex; gap: 6px; align-items: center; flex-wrap: wrap; }
.pname { font-size: 15px; }
.col { display: flex; flex-direction: column; gap: 2px; }
.subs { display: flex; flex-direction: column; gap: 10px; width: 100%; }
.sub { display: flex; gap: 8px; align-items: flex-start; }
.no { width: 20px; text-align: right; color: #909399; padding-top: 6px; }
.mt4 { margin-top: 4px; }
.dhead { display: flex; flex-direction: column; gap: 8px; margin-bottom: 10px; }
.row { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; font-size: 13px; }
.red { color: #f56c6c; }
.subhead { display: flex; align-items: center; justify-content: space-between; margin: 8px 0; }
.subhead h4 { margin: 0; }
.drow { display: flex; gap: 6px; align-items: center; margin-bottom: 8px; }
</style>
