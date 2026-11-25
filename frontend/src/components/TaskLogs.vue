<script setup>
// 任务详情里的「班次日志」：多条自由填写的记录，自动翻译成另外两种语言。
// 列出整条移交链上的日志（前面几个班写的也在）；离线写的先存手机，联网后自动提交（发件箱 type = log）。
import { computed, onUnmounted, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Loading } from '@element-plus/icons-vue'
import api from '../api'
import { useAuth } from '../stores/auth'
import { useOutbox } from '../stores/outbox'
import { translateError } from '../apiErrors'
import { fmtTime } from '../format'
import ShiftTag from './ShiftTag.vue'
import TransText from './TransText.vue'

const props = defineProps({ task: { type: Object, required: true } })
const { t, locale } = useI18n()
const auth = useAuth()
const outbox = useOutbox()
const logs = ref([])
const text = ref('')
const busy = ref(false)

let timer = null
let polls = 0
async function load() {
  const id = props.task.id
  const r = (await api.get(`/tasks/${id}/logs`)).data
  if (id !== props.task.id) return
  logs.value = r
  clearTimeout(timer)
  // 翻译在后台：有待翻译的就 3 秒后再读，最多 1 分钟
  if (r.some((x) => x.translation_status === 'pending') && polls++ < 20) timer = setTimeout(load, 3000)
}
watch(() => props.task.id, () => { polls = 0; logs.value = []; load() }, { immediate: true })
watch(() => outbox.lastSyncedTaskIds.length, load) // 离线写的同步上去了
onUnmounted(() => clearTimeout(timer))

// 还没同步的（离线写的）
const pending = computed(() => outbox.entries.filter((e) => e.type === 'log' && e.task_id === props.task.id))

async function submit() {
  const v = text.value.trim()
  if (!v) return
  busy.value = true
  try {
    const res = await outbox.submitLog(props.task, v, locale.value)
    text.value = ''
    if (res) { polls = 0; await load() } else ElMessage.warning({ message: t('outbox.savedOffline'), duration: 5000 })
  } catch (err) {
    const d = err.response?.data?.detail
    ElMessage.error(typeof d === 'string' ? translateError(d, locale.value, t) : t('common.requestFailed'))
  } finally {
    busy.value = false
  }
}
async function remove(x) {
  await ElMessageBox.confirm(t('tlog.confirmDelete'), { type: 'warning' })
  await api.delete(`/task-logs/${x.id}`)
  await load()
}
</script>

<template>
  <div class="task-logs">
    <h4>{{ t('tlog.title') }} ({{ logs.length }})</h4>
    <div v-if="!logs.length && !pending.length" class="muted small">{{ t('tlog.none') }}</div>
    <div v-for="x in logs" :key="x.id" :class="['entry', { prev: x.task_id !== task.id }]">
      <div class="meta">
        <span>{{ x.shift_date.slice(5) }}</span>
        <ShiftTag :kind="x.shift_kind" size="small" />
        <span v-if="x.team_id">{{ auth.teamLabel(x.team_id) }}</span>
        <b>{{ x.author }}</b>
        <span class="muted">{{ fmtTime(x.recorded_at) }}</span>
        <span v-if="x.translation_status === 'pending'" class="muted"><el-icon class="is-loading"><Loading /></el-icon> {{ t('tr.translating') }}</span>
        <el-button v-if="x.can_delete" link type="danger" size="small" class="del" @click="remove(x)">{{ t('common.delete') }}</el-button>
      </div>
      <TransText :tri="x.content" :src-lang="x.source_lang" field="log" />
    </div>
    <div v-for="e in pending" :key="e.key" class="entry pending">
      <div class="meta"><el-tag size="small" type="warning">⏳ {{ t('outbox.pendingShort') }}</el-tag><span class="muted">{{ fmtTime(e.log.recorded_at) }}</span></div>
      <div class="pre">{{ e.log.content }}</div>
    </div>
    <div v-if="task.perms?.log" class="add">
      <el-input v-model="text" type="textarea" :autosize="{ minRows: 2, maxRows: 8 }" maxlength="5000" :placeholder="t('tlog.placeholder')" />
      <el-button type="primary" :loading="busy" :disabled="!text.trim()" @click="submit">{{ t('tlog.add') }}</el-button>
    </div>
  </div>
</template>

<style scoped>
.entry { padding: 8px 10px; border-left: 3px solid var(--el-color-primary-light-5); background: var(--el-fill-color-light); border-radius: 4px; margin-bottom: 8px; }
.entry.prev { border-left-color: var(--el-border-color); }
.entry.pending { border-left-color: var(--el-color-warning); }
.meta { display: flex; flex-wrap: wrap; align-items: center; gap: 6px; font-size: 12px; margin-bottom: 4px; }
.del { margin-left: auto; }
.muted { color: #909399; display: inline-flex; align-items: center; gap: 4px; }
.small { font-size: 12px; }
.pre { white-space: pre-wrap; word-break: break-word; }
.add { display: flex; flex-direction: column; align-items: flex-end; gap: 6px; margin-top: 8px; }
h4 { margin: 16px 0 8px; }
</style>
