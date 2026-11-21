<script setup>
// 任务详情抽屉：内容、状态操作、人员、时间、图片、修改记录
import { computed, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { ElMessage, ElMessageBox } from 'element-plus'
import api from '../api'
import { localName, localText } from '../i18n'
import { fmtFull, isNarrow, STATUS_TYPE } from '../format'
import { preparePhotos } from '../photo'
import { useAuth } from '../stores/auth'
import { useOutbox } from '../stores/outbox'
import PhotoPicker from './PhotoPicker.vue'
import ShiftTag from './ShiftTag.vue'
import TaskForm from './TaskForm.vue'
import TaskPhotos from './TaskPhotos.vue'
import HandoverDialog from './HandoverDialog.vue'

const props = defineProps({ taskId: { type: Number, default: null } })
const visible = defineModel({ type: Boolean })
const emit = defineEmits(['changed'])
const { t, locale } = useI18n()
const auth = useAuth()
const outbox = useOutbox()

const currentId = ref(null) // 可以在移交链上前后跳转
const task = ref(null)
const hoOpen = ref(false)
const history = ref([])
const showHistory = ref(false)
const editOpen = ref(false)
const busy = ref(false)

async function load() {
  if (!currentId.value) return
  task.value = (await api.get(`/tasks/${currentId.value}`)).data
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
  task.value = null
  history.value = []
  showHistory.value = false
  load()
}
watch(showHistory, (v) => v && loadHistory())

const content = computed(() => task.value && localText(task.value.content, task.value.source_lang))
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
    await api.post(`/tasks/${task.value.id}/status`, { status })
    await changed()
  } finally {
    busy.value = false
  }
}

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
const teamLabel = (id) => localName(auth.teamById(Number(id)))
const discardReason = computed(() => task.value && localText(task.value.discard_reason, task.value.discard_reason_lang))

function parse(v) {
  if (v == null) return null
  try { return JSON.parse(v) } catch { return v }
}
function fieldLabel(f) {
  const m = /^(content|leftover)_(zh|sr|en)$/.exec(f)
  if (m) return `${t(m[1] === 'content' ? 'task.content' : 'task.leftover')} (${m[2]})`
  return { start_at: t('task.start'), end_at: t('task.end'), workers: t('task.workers') }[f] || f
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
        <span class="team">{{ localName(auth.teamById(task.team_id)) }}</span>
        <ShiftTag :kind="task.shift_kind" />
        <span class="muted">{{ task.shift_date }}</span>
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
        <div class="pre">{{ t('ho.discardReason') }}: {{ discardReason.text }}</div>
      </el-alert>

      <div class="content">{{ content.text }}</div>
      <div v-if="content.fallback || task.translation_status === 'pending'" class="muted small">
        {{ t('task.original') }} ({{ task.source_lang }}) · {{ t('task.pendingTr') }}
      </div>

      <div v-if="task.can_edit" class="actions">
        <el-button v-if="task.status === 'not_started'" type="warning" :loading="busy" @click="setStatus('in_progress')">{{ t('task.start_action') }}</el-button>
        <el-button v-if="['not_started', 'in_progress'].includes(task.status)" type="success" :loading="busy" @click="setStatus('done')">{{ t('task.done_action') }}</el-button>
        <el-button v-if="task.status === 'in_progress'" :loading="busy" @click="setStatus('not_started')">{{ t('task.undo_start') }}</el-button>
        <el-button v-if="task.status === 'done'" :loading="busy" @click="setStatus('in_progress')">{{ t('task.reopen') }}</el-button>
        <el-button @click="editOpen = true">{{ t('common.edit') }}</el-button>
        <template v-if="['not_started', 'in_progress'].includes(task.status)">
          <el-button type="primary" plain @click="hoOpen = true">{{ t('ho.handover') }}</el-button>
          <el-button type="danger" plain @click="discard">{{ t('ho.discard') }}</el-button>
        </template>
      </div>

      <el-descriptions :column="1" border size="small" class="meta">
        <el-descriptions-item :label="t('task.workers')">
          <el-tag v-for="w in task.workers" :key="w.id" size="small" class="wtag">{{ w.name }}</el-tag>
          <span v-if="!task.workers.length" class="muted">{{ t('task.noWorkers') }}</span>
        </el-descriptions-item>
        <el-descriptions-item :label="t('task.start')">{{ fmtFull(task.start_at) }}</el-descriptions-item>
        <el-descriptions-item :label="t('task.end')">{{ fmtFull(task.end_at) }}</el-descriptions-item>
        <el-descriptions-item v-if="task.confirmed_by" :label="t('task.confirmedBy')">{{ task.confirmed_by_name }} · {{ fmtFull(task.confirmed_at) }}</el-descriptions-item>
        <el-descriptions-item :label="t('task.publisher')">{{ task.created_by_name }} · {{ fmtFull(task.recorded_at) }}</el-descriptions-item>
        <el-descriptions-item :label="t('task.updater')">{{ task.updated_by_name }} · {{ fmtFull(task.updated_at) }}</el-descriptions-item>
        <el-descriptions-item v-if="leftover.text" :label="t('task.leftover')"><span class="pre">{{ leftover.text }}</span></el-descriptions-item>
      </el-descriptions>

      <h4>{{ t('photo.title') }} ({{ task.attachments.length }})</h4>
      <TaskPhotos :photos="task.attachments" :can-delete="task.can_edit" @delete="deletePhoto" />
      <PhotoPicker v-if="task.can_edit" class="mt" @pick="addPhotos" />

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
    <HandoverDialog v-if="task" v-model="hoOpen" :task-ids="[task.id]" :team-id="task.team_id" @done="changed" />
  </el-drawer>
</template>

<style scoped>
.head { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.team { font-weight: 600; }
.content { font-size: 16px; line-height: 1.6; margin: 12px 0 4px; white-space: pre-wrap; word-break: break-word; }
.muted { color: #909399; }
.small { font-size: 12px; }
.actions { display: flex; gap: 8px; flex-wrap: wrap; margin: 12px 0; }
.actions .el-button + .el-button { margin-left: 0; }
.meta { margin: 12px 0; }
.wtag { margin: 2px 4px 2px 0; }
.pre { white-space: pre-wrap; }
.mt { margin-top: 12px; }
h4 { margin: 16px 0 8px; }
</style>
