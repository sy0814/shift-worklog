<script setup>
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { Picture } from '@element-plus/icons-vue'
import { localName, localText } from '../i18n'
import { fmtTime, STATUS_TYPE } from '../format'
import { useAuth } from '../stores/auth'
import { useOutbox } from '../stores/outbox'
import ShiftTag from './ShiftTag.vue'
import TransText from './TransText.vue'

const props = defineProps({ task: { type: Object, required: true } })
const { t } = useI18n()
const auth = useAuth()
const outbox = useOutbox()
// 离线时点了开始 / 完成还没同步的，按点的状态显示
const pending = computed(() => { const p = outbox.pendingStatus(props.task.id); return p && p !== props.task.status ? p : null })
const status = computed(() => pending.value || props.task.status)
const leftover = computed(() => localText(props.task.leftover, props.task.leftover_source_lang))
// 项目设了计划开始、还没到：写「计划 … 开始」（这之前它不在待办里，只在项目、任务页能看到）
const planned = computed(() => props.task.visible_from && new Date(props.task.chain_started_at) > new Date())
</script>

<template>
  <div :class="['card', `st-${status}`, { overdue: task.overdue }]">
    <div class="row1">
      <el-tag :type="STATUS_TYPE[status]" size="small" effect="dark">{{ t(`status.${status}`) }}</el-tag>
      <el-tag v-if="pending" type="warning" size="small" effect="plain">⏳ {{ t('outbox.pendingShort') }}</el-tag>
      <span class="team">{{ auth.teamLabel(task.team_id) }}</span>
      <ShiftTag :kind="task.shift_kind" />
      <span class="muted">{{ task.shift_date.slice(5) }}</span>
      <el-tag v-if="planned" type="warning" size="small" effect="plain">⏰ {{ t('proj.startTag', { t: fmtTime(task.chain_started_at) }) }}</el-tag>
      <el-tag v-if="task.overdue" type="danger" size="small" effect="dark">{{ t('overdue.badge') }} {{ Math.floor(task.age_hours) }}h</el-tag>
      <el-tag v-if="task.inspection_id" size="small" type="success" effect="plain">{{ t('insp.tag') }}</el-tag>
      <el-tag v-if="task.project" size="small" type="primary" effect="plain" class="ptag">📁 {{ localText(task.project.name, task.project.source_lang).text }} {{ task.project.done }}/{{ task.project.total }}</el-tag>
      <el-tag v-if="task.kind === 'fault' || task.kind === 'maintenance'" size="small" :type="task.kind === 'fault' ? 'danger' : 'warning'" effect="plain" class="ptag">{{ t('task.kinds.' + task.kind) }}</el-tag>
      <el-tag v-if="task.log_count" size="small" type="info" effect="plain" class="ptag" :title="t('tlog.countHint', { n: task.log_count })">📝 {{ task.log_count }}</el-tag>
      <el-tag v-if="task.equipment" size="small" type="info" effect="plain" class="ptag">⚙ {{ task.equipment.code }} {{ localText(task.equipment.name, task.equipment.source_lang).text }}</el-tag>
      <el-tag v-if="task.transferable === false" size="small" type="info" effect="plain">🔒 {{ t('task.notTransferable') }}</el-tag>
      <el-tag v-if="task.handover_in" size="small" effect="plain">← {{ auth.teamLabel(task.handover_in.team_id) }}</el-tag>
      <el-tag v-if="task.handover_out" size="small" type="warning" effect="plain">→ {{ auth.teamLabel(task.handover_out.team_id) }}</el-tag>
      <span class="spacer" />
      <span v-if="task.attachments.length" class="muted"><el-icon><Picture /></el-icon> {{ task.attachments.length }}</span>
    </div>
    <TransText class="content" :tri="task.content" :src-lang="task.source_lang" field="content" :manual-fields="task.manual_fields || []" compact />
    <div v-if="leftover.text" class="leftover">⚠ {{ leftover.text }}</div>
    <div class="row3 muted">
      <span v-if="task.lead" class="lead">★ {{ t('lead.title') }}：{{ task.lead.name }}</span>
      <span v-if="task.workers.length">👷 {{ task.workers.map((w) => w.name).join('、') }}</span>
      <span>✎ {{ $pn(task.created_by_name) }} {{ fmtTime(task.recorded_at) }}</span>
      <span v-if="task.updated_by !== task.created_by || task.updated_at !== task.created_at">↻ {{ $pn(task.updated_by_name) }} {{ fmtTime(task.updated_at) }}</span>
    </div>
  </div>
</template>

<style scoped>
.card { background: #fff; border-radius: 8px; padding: 10px 12px; border-left: 4px solid #c0c4cc; cursor: pointer; }
.card:hover { box-shadow: 0 2px 8px rgba(0,0,0,.08); }
.st-in_progress { border-left-color: #e6a23c; }
.st-done { border-left-color: #67c23a; }
.st-discarded { border-left-color: #f56c6c; opacity: .75; }
.st-handed_over { border-left-color: #409eff; opacity: .8; }
.card.overdue { border-left-color: #f56c6c; background: #fef0f0; }
.row1 { display: flex; align-items: center; gap: 6px; flex-wrap: wrap; }
.team { font-weight: 600; }
.spacer { flex: 1; }
.content { margin: 6px 0 4px; line-height: 1.5; }
.content :deep(.text) { display: -webkit-box; -webkit-line-clamp: 3; -webkit-box-orient: vertical; overflow: hidden; }
.lead { color: #b88230; }
.orig { color: #b1b3b8; font-size: 12px; }
.leftover { color: #b88230; font-size: 13px; margin-bottom: 4px; }
.row3 { display: flex; gap: 12px; flex-wrap: wrap; font-size: 12px; }
.muted { color: #909399; display: inline-flex; align-items: center; gap: 2px; }
.ptag { max-width: 240px; overflow: hidden; text-overflow: ellipsis; }
</style>
