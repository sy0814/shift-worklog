<script setup>
// 项目详情（首页交接班里点项目文件夹打开）：项目信息、进度、全部小项目；点小项目打开任务详情，右上角「添加小项目」
import { computed, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import dayjs from 'dayjs'
import api from '../api'
import { localName, localText } from '../i18n'
import { isNarrow } from '../format'
import { useAuth } from '../stores/auth'
import ShiftTag from './ShiftTag.vue'
import TaskCard from './TaskCard.vue'
import TaskDetail from './TaskDetail.vue'

const props = defineProps({ modelValue: Boolean, projectId: { type: Number, default: null } })
const emit = defineEmits(['update:modelValue', 'add', 'changed'])
const { t } = useI18n()
const auth = useAuth()
const visible = computed({ get: () => props.modelValue, set: (v) => emit('update:modelValue', v) })
const p = ref(null)
const loading = ref(false)

async function load() {
  if (!props.projectId) return
  loading.value = true
  try { p.value = (await api.get(`/projects/${props.projectId}`)).data } finally { loading.value = false }
}
watch(() => [props.modelValue, props.projectId], ([open]) => { if (open) load() }, { immediate: true })
defineExpose({ load })

const name = computed(() => (p.value ? localText(p.value.name, p.value.source_lang).text : ''))
const pct = computed(() => (p.value?.total ? Math.round(((p.value.done + p.value.discarded) / p.value.total) * 100) : 0))
const taskOpen = ref(false)
const taskId = ref(null)
function openTask(s) { taskId.value = s.id; taskOpen.value = true }
function changed() { load(); emit('changed') }
</script>

<template>
  <el-drawer v-model="visible" :size="isNarrow() ? '100%' : '600px'" :title="name" append-to-body class="proj-drawer-x">
    <div v-loading="loading" class="pd-body">
      <template v-if="p">
        <div class="pd-row">
          <el-tag effect="plain">{{ localName(auth.teamById(p.team_id)) }}</el-tag>
          <template v-if="p.shift_date"><ShiftTag :kind="p.shift_kind" /> <span>{{ p.shift_date.slice(5) }}</span></template>
          <el-tag v-if="p.closed_at" type="success">{{ t('proj.closedTag') }} {{ dayjs(p.closed_at).format('MM-DD HH:mm') }}</el-tag>
          <span class="pd-grow" />
          <el-button v-if="p.can_add" type="primary" size="small" @click="emit('add', p)">+ {{ t('proj.addItem') }}</el-button>
        </div>
        <el-progress :percentage="pct" :status="p.closed_at ? 'success' : undefined" :stroke-width="12" />
        <div class="pd-muted">
          {{ t('proj.counts', { done: p.done, total: p.total, open: p.open }) }}<template v-if="p.discarded"> · {{ t('proj.discarded', { n: p.discarded }) }}</template>
          · {{ $pn(p.created_by_name) }} {{ dayjs(p.created_at).format('MM-DD HH:mm') }}
          · {{ p.transferable ? t('proj.transferableHint') : t('proj.fixedHint') }}
        </div>
        <h4 class="pd-h">{{ t('proj.subs') }}</h4>
        <div v-if="!p.subs.length" class="pd-muted">{{ t('proj.noItems') }}</div>
        <TaskCard v-for="s in p.subs" :key="s.id" :task="s" class="pd-card" @click="openTask(s)" />
      </template>
    </div>
    <TaskDetail v-model="taskOpen" :task-id="taskId" @changed="changed" />
  </el-drawer>
</template>

<style scoped>
.pd-body { display: flex; flex-direction: column; gap: 10px; min-height: 120px; }
.pd-row { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; font-size: 13px; }
.pd-grow { flex: 1; }
.pd-muted { color: #909399; font-size: 13px; line-height: 1.5; }
.pd-h { margin: 8px 0 0; font-size: 15px; }
.pd-card { cursor: pointer; }
</style>
