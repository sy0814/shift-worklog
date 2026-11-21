<script setup>
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { Picture } from '@element-plus/icons-vue'
import { localName, localText } from '../i18n'
import { fmtTime, STATUS_TYPE } from '../format'
import { useAuth } from '../stores/auth'
import ShiftTag from './ShiftTag.vue'

const props = defineProps({ task: { type: Object, required: true } })
const { t } = useI18n()
const auth = useAuth()
const content = computed(() => localText(props.task.content, props.task.source_lang))
const leftover = computed(() => localText(props.task.leftover, props.task.leftover_source_lang))
</script>

<template>
  <div :class="['card', `st-${task.status}`]">
    <div class="row1">
      <el-tag :type="STATUS_TYPE[task.status]" size="small" effect="dark">{{ t(`status.${task.status}`) }}</el-tag>
      <span class="team">{{ localName(auth.teamById(task.team_id)) }}</span>
      <ShiftTag :kind="task.shift_kind" />
      <span class="muted">{{ task.shift_date.slice(5) }}</span>
      <span class="spacer" />
      <span v-if="task.attachments.length" class="muted"><el-icon><Picture /></el-icon> {{ task.attachments.length }}</span>
    </div>
    <div class="content">{{ content.text }}<span v-if="content.fallback" class="orig"> · {{ t('task.original') }}</span></div>
    <div v-if="leftover.text" class="leftover">⚠ {{ leftover.text }}</div>
    <div class="row3 muted">
      <span v-if="task.workers.length">👷 {{ task.workers.map((w) => w.name).join('、') }}</span>
      <span>✎ {{ task.created_by_name }} {{ fmtTime(task.recorded_at) }}</span>
      <span v-if="task.updated_by !== task.created_by || task.updated_at !== task.created_at">↻ {{ task.updated_by_name }} {{ fmtTime(task.updated_at) }}</span>
    </div>
  </div>
</template>

<style scoped>
.card { background: #fff; border-radius: 8px; padding: 10px 12px; border-left: 4px solid #c0c4cc; cursor: pointer; }
.card:hover { box-shadow: 0 2px 8px rgba(0,0,0,.08); }
.st-in_progress { border-left-color: #e6a23c; }
.st-done { border-left-color: #67c23a; }
.st-discarded { border-left-color: #f56c6c; }
.row1 { display: flex; align-items: center; gap: 6px; flex-wrap: wrap; }
.team { font-weight: 600; }
.spacer { flex: 1; }
.content { margin: 6px 0 4px; line-height: 1.5; white-space: pre-wrap; word-break: break-word; display: -webkit-box; -webkit-line-clamp: 4; -webkit-box-orient: vertical; overflow: hidden; }
.orig { color: #b1b3b8; font-size: 12px; }
.leftover { color: #b88230; font-size: 13px; margin-bottom: 4px; }
.row3 { display: flex; gap: 12px; flex-wrap: wrap; font-size: 12px; }
.muted { color: #909399; display: inline-flex; align-items: center; gap: 2px; }
</style>
