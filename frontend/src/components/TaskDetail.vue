<script setup>
// 任务详情抽屉：内容、状态操作、人员、时间、图片、修改记录
import { computed, onUnmounted, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Loading } from '@element-plus/icons-vue'
import api from '../api'
import { localName, localText } from '../i18n'
import { fmtFull, isNarrow, STATUS_TYPE } from '../format'
import { preparePhotos } from '../photo'
import { useAuth } from '../stores/auth'
import { useOutbox } from '../stores/outbox'
import { translateError } from '../apiErrors'
import PhotoPicker from './PhotoPicker.vue'
import ShiftTag from './ShiftTag.vue'
import TaskForm from './TaskForm.vue'
import TaskPhotos from './TaskPhotos.vue'
import HandoverDialog from './HandoverDialog.vue'
import TransText from './TransText.vue'
import TranslationEditor from './TranslationEditor.vue'

const props = defineProps({ taskId: { type: Number, default: null } })
const visible = defineModel({ type: Boolean })
const emit = defineEmits(['changed'])
const { t, locale } = useI18n()
const auth = useAuth()
const outbox = useOutbox()

const currentId = ref(null) // 可以在移交链上前后跳转
const task = ref(null)
const hoOpen = ref(false)
const trOpen = ref(false)
const retranslating = ref(false)

// 翻译在后台进行：待翻译时每 3 秒刷新一次，最多 1 分钟
let pollTimer = null
let pollCount = 0
function schedulePoll() {
  clearTimeout(pollTimer)
  if (!visible.value || task.value?.translation_status !== 'pending' || pollCount >= 20) return
  pollTimer = setTimeout(async () => {
    pollCount++
    const id = currentId.value
    const fresh = (await api.get(`/tasks/${id}`)).data
    if (id === currentId.value) task.value = fresh
    if (fresh.translation_status !== 'pending') emit('changed') // 翻译好了，让列表也刷新
    schedulePoll()
  }, 3000)
}
watch(() => task.value?.translation_status, () => schedulePoll())
watch(visible, (v) => !v && clearTimeout(pollTimer))
onUnmounted(() => clearTimeout(pollTimer))

async function retranslate() {
  retranslating.value = true
  try {
    task.value = (await api.post(`/tasks/${task.value.id}/retranslate`)).data
    emit('changed')
  } finally {
    retranslating.value = false
  }
}
const history = ref([])
const showHistory = ref(false)
const editOpen = ref(false)
const busy = ref(false)

// 离线时点了开始 / 完成、还没同步的：先按点的状态显示，标「待同步」
function overlay(tk) {
  const p = tk && outbox.pendingStatus(tk.id)
  return p && p !== tk.status ? { ...tk, status: p, pendingSync: true } : tk
}
async function load() {
  if (!currentId.value) return
  task.value = overlay((await api.get(`/tasks/${currentId.value}`)).data)
  if (showHistory.value) await loadHistory()
}
async function loadHistory() {
  history.value = (await api.get(`/tasks/${currentId.value}/history`)).data
}
watch(() => [visible.value, props.taskId], ([v]) => {
  if (v) goTo(props.taskId)
}, { immediate: true })

function goTo(id) {
  currentId.value = id
  pollCount = 0
  task.value = null
  history.value = []
  showHistory.value = false
  load()
}
watch(showHistory, (v) => v && loadHistory())

const leftover = computed(() => task.value && localText(task.value.leftover, task.value.leftover_source_lang))

async function changed() {
  await load()
  emit('changed')
}

async function setStatus(status) {
  if (status === 'done') {
    await ElMessageBox.confirm(t('task.confirmDone'), { type: 'success' })
  }
  busy.value = true
  try {
    const res = await outbox.submitStatus(task.value, status)
    if (res) {
      await changed()
    } else { // 断网：存在手机上，联网后自动提交
      task.value = { ...task.value, status, pendingSync: true }
      ElMessage.warning({ message: t('outbox.statusSaved'), duration: 5000 })
      emit('changed')
    }
  } catch (err) {
    const d = err.response?.data?.detail
    ElMessage.error(typeof d === 'string' ? translateError(d, locale.value, t) : t('common.requestFailed'))
    await load()
  } finally {
    busy.value = false
  }
}
// 发件箱同步完了 → 重新读一次
watch(() => outbox.lastSyncedTaskIds.length, () => visible.value && task.value && load())

async function addPhotos(files) {
  busy.value = true
  try {
    const ok = await outbox.submitPhotos(task.value.id, await preparePhotos(files))
    if (!ok) ElMessage.warning({ message: t('outbox.savedOffline'), duration: 5000 })
    await changed()
  } finally {
    busy.value = false
  }
}

async function discard() {
  const { value } = await ElMessageBox.prompt(t('ho.discardReason'), t('ho.discard'), {
    inputType: 'textarea', inputPlaceholder: t('ho.discardPh'), confirmButtonClass: 'el-button--danger',
    inputValidator: (v) => !!v?.trim() || t('ho.discardPh'),
  })
  await api.post(`/tasks/${task.value.id}/discard`, { reason: value.trim(), lang: locale.value })
  await changed()
}

async function deletePhoto(p) {
  await ElMessageBox.confirm(t('photo.confirmRemove'), { type: 'warning' })
  await api.delete(`/attachments/${p.id}`)
  await changed()
}

// 修改记录：状态变更只显示状态那一行（附带的时间、确认人等字段仍在留痕里），语言标记字段不显示
const shownHistory = computed(() => history.value.filter((h) => {
  if (['source_lang', 'leftover_source_lang'].includes(h.field)) return false
  if (h.action === 'status') return h.field === 'status'
  if (h.action === 'handover') return h.field === 'to_team'
  if (h.action === 'discard') return /^discard_reason_(zh|sr|en)$/.test(h.field)
  return true
}))
const teamLabel = (id) => auth.teamLabel(Number(id))

function parse(v) {
  if (v == null) return null
  try { return JSON.parse(v) } catch { return v }
}
function fieldLabel(f) {
  const m = /^(content|leftover|discard_reason)_(zh|sr|en)$/.exec(f)
  if (m) return `${t('tr.fields.' + m[1])} (${m[2]})`
  return { start_at: t('task.start'), end_at: t('task.end'), workers: t('lead.members'), lead_worker: t('lead.title') }[f] || f
}
function fmtVal(f, v) {
  v = parse(v)
  if (v == null || v === '') return '∅'
  if (Array.isArray(v)) return v.join('、') || '∅'
  if (f === 'start_at' || f === 'end_at') return fmtFull(String(v).replace(' ', 'T'))
  const str = String(v)
  return str.length > 60 ? str.slice(0, 60) + '…' : str
}
function histText(h) {
  if (h.action === 'attach' || h.action === 'detach') return h.new_value || h.old_value
  if (h.action === 'create') return ''
  if (h.action === 'handover') return `→ ${teamLabel(h.new_value)}`
  if (h.action === 'discard') return parse(h.new_value)
  if (h.action === 'translate') {
    const v = parse(h.new_value) || {}
    return `${fieldLabel(h.field + '_' + locale.value)}: ${fmtVal('', v[h.field + '_' + locale.value])}`
  }
  if (h.action === 'retranslate') return ''
  if (h.action === 'receive') {
    const v = parse(h.new_value) || {}
    return `${teamLabel(v.from_team_id)} → ${teamLabel(v.to_team_id)}${v.note ? ' · ' + v.note : ''}`
  }
  if (h.field === 'status') return `${t('status.' + h.old_value)} → ${t('status.' + h.new_value)}`
  return `${fieldLabel(h.field)}: ${fmtVal(h.field, h.old_value)} → ${fmtVal(h.field, h.new_value)}`
}
</script>

<template>
  <el-drawer v-model="visible" :size="isNarrow() ? '100%' : '560px'" :title="task ? `#${task.id}` : ''" append-to-body>
    <div v-if="task" class="detail">
      <div class="head">
        <el-tag :type="STATUS_TYPE[task.status]" effect="dark">{{ t(`status.${task.status}`) }}</el-tag>
        <span class="team">{{ auth.teamLabel(task.team_id) }}</span>
        <ShiftTag :kind="task.shift_kind" />
        <span class="muted">{{ task.shift_date }}</span>
        <el-tag v-if="task.inspection_id" size="small" type="success" effect="plain">{{ t('insp.tag') }} · {{ task.inspection_name }}</el-tag>
        <el-tag v-if="task.equipment" size="small" type="info" effect="plain">⚙ {{ task.equipment.code }} {{ localText(task.equipment.name, task.equipment.source_lang).text }}</el-tag>
        <el-tag v-if="task.project" size="small" type="primary" effect="plain">📁 {{ localText(task.project.name, task.project.source_lang).text }} · {{ task.project.done }}/{{ task.project.total }}<template v-if="!task.project.transferable"> · {{ t('proj.fixed') }}</template></el-tag>
      </div>

      <el-alert v-if="task.overdue" type="error" :closable="false" show-icon class="mt"
                :title="`${t('overdue.badge')} · ${t('overdue.hours', { n: Math.floor(task.age_hours) })}${task.handover_count ? ' · ' + t('ho.times', { n: task.handover_count }) : ''}`" />
      <el-alert v-if="task.handover_in" type="info" :closable="false" class="mt"
                :title="`${t('ho.from', { team: teamLabel(task.handover_in.team_id) })} · ${task.handover_in.by_name} · ${fmtFull(task.handover_in.at)}`">
        <el-button link type="primary" @click="goTo(task.handover_in.task_id)">{{ t('ho.viewSource') }} #{{ task.handover_in.task_id }}</el-button>
      </el-alert>
      <el-alert v-if="task.handover_out" type="warning" :closable="false" class="mt"
                :title="`${t('ho.toTeam', { team: teamLabel(task.handover_out.team_id) })} · ${task.handover_out.by_name} · ${fmtFull(task.handover_out.at)}`">
        <div v-if="task.handover_out.note" class="pre">{{ task.handover_out.note }}</div>
        <el-button link type="primary" @click="goTo(task.handover_out.task_id)">{{ t('ho.viewTarget') }} #{{ task.handover_out.task_id }}</el-button>
      </el-alert>
      <el-alert v-if="task.status === 'discarded'" type="error" :closable="false" class="mt"
                :title="`${t('ho.discarded')} · ${task.discarded_by_name} · ${fmtFull(task.discarded_at)}`">
        <b>{{ t('ho.discardReason') }}:</b>
        <TransText :tri="task.discard_reason" :src-lang="task.discard_reason_lang" field="discard_reason" :manual-fields="task.manual_fields" />
      </el-alert>

      <TransText class="content" :tri="task.content" :src-lang="task.source_lang" field="content" :manual-fields="task.manual_fields" />
      <div class="trbar small">
        <span v-if="task.translation_status === 'pending'" class="muted"><el-icon class="is-loading"><Loading /></el-icon> {{ t('tr.translating') }}</span>
        <span v-if="task.translation_status === 'failed'" class="err">{{ t('tr.failed') }}<template v-if="task.translation_error">: {{ task.translation_error }}</template></span>
        <el-button v-if="task.can_correct" link type="primary" size="small" @click="trOpen = true">{{ t('tr.correct') }}</el-button>
        <el-button v-if="task.translation_status !== 'done' && task.can_correct" link type="primary" size="small" :loading="retranslating" @click="retranslate">{{ t('tr.retry') }}</el-button>
      </div>

      <el-alert v-if="task.pendingSync" type="warning" :closable="false" class="mt" show-icon :title="t('outbox.pendingStatus')" />
      <div v-if="task.status === 'done' && !task.perms?.edit && !task.perms?.status" class="muted small mt">🔒 {{ t('task.doneLocked') }}</div>
      <div v-if="task.perms?.status || task.perms?.edit || task.perms?.handover || task.perms?.discard" class="actions">
        <template v-if="task.perms?.status">
        <el-button v-if="task.status === 'not_started'" type="warning" :loading="busy" @click="setStatus('in_progress')">{{ t('task.start_action') }}</el-button>
        <el-button v-if="['not_started', 'in_progress'].includes(task.status)" type="success" :loading="busy" @click="setStatus('done')">{{ t('task.done_action') }}</el-button>
        <el-button v-if="task.status === 'in_progress'" :loading="busy" @click="setStatus('not_started')">{{ t('task.undo_start') }}</el-button>
        <el-button v-if="task.status === 'done'" :loading="busy" @click="setStatus('in_progress')">{{ t('task.reopen') }}</el-button>
        </template>
        <el-button v-if="task.perms?.edit" @click="editOpen = true">{{ t('common.edit') }}</el-button>
        <el-button v-if="task.perms?.handover" type="primary" plain @click="hoOpen = true">{{ t('ho.handover') }}</el-button>
        <el-button v-if="task.perms?.discard" type="danger" plain @click="discard">{{ t('ho.discard') }}</el-button>
      </div>

      <el-descriptions :column="1" border size="small" class="meta">
        <el-descriptions-item :label="t('lead.title')">
          <el-tag v-if="task.lead" size="small" type="warning" class="wtag">★ {{ task.lead.name }}</el-tag>
          <span v-else class="muted">{{ t('lead.none') }}</span>
        </el-descriptions-item>
        <el-descriptions-item :label="t('lead.members')">
          <el-tag v-for="w in task.workers" :key="w.id" size="small" class="wtag">{{ w.name }}</el-tag>
          <span v-if="!task.workers.length" class="muted">{{ t('task.noWorkers') }}</span>
        </el-descriptions-item>
        <el-descriptions-item :label="t('task.start')">{{ fmtFull(task.start_at) }}</el-descriptions-item>
        <el-descriptions-item :label="t('task.end')">{{ fmtFull(task.end_at) }}</el-descriptions-item>
        <el-descriptions-item v-if="task.confirmed_by" :label="t('task.confirmedBy')">{{ task.confirmed_by_name }} · {{ fmtFull(task.confirmed_at) }}</el-descriptions-item>
        <el-descriptions-item :label="t('task.publisher')">{{ task.created_by_name }} · {{ fmtFull(task.recorded_at) }}</el-descriptions-item>
        <el-descriptions-item :label="t('task.updater')">{{ task.updated_by_name }} · {{ fmtFull(task.updated_at) }}</el-descriptions-item>
        <el-descriptions-item v-if="leftover.text" :label="t('task.leftover')">
          <TransText :tri="task.leftover" :src-lang="task.leftover_source_lang" field="leftover" :manual-fields="task.manual_fields" />
        </el-descriptions-item>
      </el-descriptions>

      <h4>{{ t('photo.title') }} ({{ task.attachments.length }})</h4>
      <TaskPhotos :photos="task.attachments" :can-delete="(p) => p.can_delete" @delete="deletePhoto" />
      <PhotoPicker v-if="task.perms?.photo" class="mt" @pick="addPhotos" />

      <el-collapse class="mt" @change="(v) => (showHistory = v.includes('h'))">
        <el-collapse-item :title="t('task.history')" name="h">
          <el-timeline v-if="shownHistory.length">
            <el-timeline-item v-for="h in shownHistory" :key="h.id" :timestamp="`${fmtFull(h.at)} · ${h.user_name ?? ''}`" placement="top">
              <b>{{ t('history.' + h.action) }}</b> <span class="small">{{ histText(h) }}</span>
            </el-timeline-item>
          </el-timeline>
        </el-collapse-item>
      </el-collapse>
    </div>
    <el-skeleton v-else :rows="6" animated />
    <TaskForm v-if="task" v-model="editOpen" :task="task" @saved="changed" />
    <TranslationEditor v-if="task" v-model="trOpen" :task="task" @saved="changed" />
    <HandoverDialog v-if="task" v-model="hoOpen" :task-ids="[task.id]" :team-id="task.team_id" @done="changed" />
  </el-drawer>
</template>

<style scoped>
.head { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.team { font-weight: 600; }
.content { font-size: 16px; line-height: 1.6; margin: 12px 0 4px; white-space: pre-wrap; word-break: break-word; }
.muted { color: #909399; display: inline-flex; align-items: center; gap: 4px; }
.trbar { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; min-height: 20px; }
.err { color: #f56c6c; }
.small { font-size: 12px; }
.actions { display: flex; gap: 8px; flex-wrap: wrap; margin: 12px 0; }
.actions .el-button + .el-button { margin-left: 0; }
.meta { margin: 12px 0; }
.wtag { margin: 2px 4px 2px 0; }
.pre { white-space: pre-wrap; }
.mt { margin-top: 12px; }
h4 { margin: 16px 0 8px; }
</style>
