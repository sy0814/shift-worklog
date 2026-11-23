<script setup>
// 首页点「当前在班 / 下一个接班」弹出：这个班次各班组在岗的人和状态（忙碌 / 空闲 / 请假），可勾选后快捷添加任务
import { computed, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import api from '../api'
import { localName, localText } from '../i18n'
import { isNarrow } from '../format'
import { useAuth } from '../stores/auth'
import ShiftTag from './ShiftTag.vue'
import WorkerAvatar from './WorkerAvatar.vue'

const props = defineProps({ which: { type: String, default: 'current' } })
const visible = defineModel({ type: Boolean })
const emit = defineEmits(['add', 'open-task'])
const { t } = useI18n()
const auth = useAuth()
const data = ref(null)
const loading = ref(false)
const picked = ref([])

async function load() {
  loading.value = true
  try {
    data.value = (await api.get('/duty', { params: { which: props.which } })).data
  } finally {
    loading.value = false
  }
}
watch(visible, (v) => { if (v) { picked.value = []; load() } })
defineExpose({ load })

const teamName = (id) => localName(auth.teamById(id))
const ST_TYPE = { busy: 'warning', idle: 'success', leave: 'info', sick: 'info', absent: 'danger', off: 'info' }
const canPick = (r) => data.value?.can_add && (r.status === 'busy' || r.status === 'idle')
function toggle(id, v) {
  picked.value = v ? [...picked.value, id] : picked.value.filter((x) => x !== id)
}
const title = computed(() => data.value
  ? t('duty.title', { shift: `${data.value.shift_date.slice(5)} ${t('shift.' + data.value.shift_kind)}` }) : '')

function addTask() {
  // 管理员默认派给这个班次的倒班班组；班长派给自己的班组
  const team = auth.isAdmin ? data.value.main_team_id : auth.user.team_id
  emit('add', { worker_ids: [...picked.value], team_id: team })
  visible.value = false
}
</script>

<template>
  <el-drawer v-model="visible" :title="title" :size="isNarrow() ? '100%' : '520px'" append-to-body>
    <div v-loading="loading" class="duty">
      <template v-if="data">
        <div class="counts">
          <ShiftTag :kind="data.shift_kind" />
          <el-tag type="primary">{{ t('duty.onDuty', { n: data.counts.on_duty }) }}</el-tag>
          <el-tag type="warning">{{ t('duty.busy', { n: data.counts.busy }) }}</el-tag>
          <el-tag type="success">{{ t('duty.idle', { n: data.counts.idle }) }}</el-tag>
          <el-tag v-if="data.counts.absent" type="info">{{ t('duty.absent', { n: data.counts.absent }) }}</el-tag>
        </div>
        <div v-if="data.can_add" class="muted small">{{ t('duty.select') }}</div>
        <div v-if="!data.teams.some((x) => x.workers.length)" class="muted">{{ t('duty.none') }}</div>

        <section v-for="team in data.teams" :key="team.team_id" class="team">
          <h4>{{ teamName(team.team_id) }} <el-tag size="small" round>{{ team.workers.filter((w) => w.status === 'busy' || w.status === 'idle').length }}</el-tag></h4>
          <div v-for="r in team.workers" :key="r.worker.id" :class="['person', `s-${r.status}`]">
            <el-checkbox v-if="canPick(r)" :model-value="picked.includes(r.worker.id)" @change="(v) => toggle(r.worker.id, v)" />
            <span v-else class="nocheck" />
            <WorkerAvatar :worker="r.worker" :size="40" />
            <div class="info">
              <div class="name">
                <b>{{ r.worker.name }}</b>
                <el-tag :type="ST_TYPE[r.status]" size="small" effect="dark">{{ t('duty.st.' + r.status) }}</el-tag>
                <el-tag v-if="r.support" size="small" effect="plain">{{ t('duty.support') }} · {{ teamName(r.worker.team_id) }}</el-tag>
              </div>
              <div v-for="task in r.tasks" :key="task.id" class="task" @click="emit('open-task', task.id)">
                <span :class="['dot', task.status]" />
                <span v-if="task.is_lead" class="lead">★</span>
                <span class="tt">{{ localText(task.content, task.source_lang).text }}</span>
              </div>
            </div>
          </div>
        </section>
      </template>
    </div>
    <template v-if="data?.can_add" #footer>
      <el-button type="primary" :disabled="!picked.length" style="width: 100%" @click="addTask">{{ t('duty.addTask', { n: picked.length }) }}</el-button>
    </template>
  </el-drawer>
</template>

<style scoped>
.counts { display: flex; gap: 6px; flex-wrap: wrap; align-items: center; margin-bottom: 8px; }
.muted { color: #909399; }
.small { font-size: 12px; margin-bottom: 8px; }
.team h4 { margin: 14px 0 6px; display: flex; gap: 6px; align-items: center; }
.person { display: flex; gap: 10px; align-items: flex-start; padding: 8px 0; border-bottom: 1px solid #f2f3f5; }
.person.s-leave, .person.s-sick, .person.s-absent, .person.s-off { opacity: .6; }
.nocheck { width: 14px; flex: none; }
.person :deep(.el-checkbox) { margin-top: 10px; height: auto; }
.info { flex: 1; min-width: 0; }
.name { display: flex; gap: 6px; align-items: center; flex-wrap: wrap; }
.task { display: flex; gap: 6px; align-items: center; font-size: 12.5px; color: #606266; margin-top: 3px; cursor: pointer; }
.task:hover .tt { color: #409eff; }
.tt { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; min-width: 0; }
.dot { width: 7px; height: 7px; border-radius: 50%; background: #c0c4cc; flex: none; }
.dot.in_progress { background: #e6a23c; }
.lead { color: #e6a23c; }
</style>
