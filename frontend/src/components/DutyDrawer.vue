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
import OvertimeDialog from './OvertimeDialog.vue'
import WhyDialog from './WhyDialog.vue'
import { breaks, fullHours, splitHours } from '../cycle'
import dayjs from 'dayjs'

const props = defineProps({ which: { type: String, default: 'current' } })
const visible = defineModel({ type: Boolean })
const emit = defineEmits(['add', 'open-task', 'loaded'])
const { t, locale } = useI18n()
const auth = useAuth()
const data = ref(null)
const loading = ref(false)
const picked = ref([])

// 角色名（上面一块的标题和每人的角色标签用）
const roles = ref([])
const roleName = (id) => { const r = roles.value.find((x) => x.id === id); return r ? r[`name_${locale.value}`] : '' }
const topTitle = computed(() => roles.value.filter((r) => r.show_on_top).map((r) => r[`name_${locale.value}`]).join(' / '))

async function load() {
  if (!roles.value.length) api.get('/roles', { silent: true }).then((r) => { roles.value = r.data }).catch(() => {})
  loading.value = true
  try {
    data.value = (await api.get('/duty', { params: { which: props.which } })).data
    emit('loaded', props.which, data.value) // 首页卡片上的人数跟着更新
  } finally {
    loading.value = false
  }
}
watch(visible, (v) => { if (v) { picked.value = []; load() } })
defineExpose({ load })

// 「为什么？」：这个人这个班次日的排班是怎么来的
const why = ref({ open: false, id: 0, title: '' })
function openWhy(w) {
  why.value = { open: true, id: w.id, title: `${w.name} · ${data.value.shift_date}` }
}

const teamName = (id) => localName(auth.teamById(id))
const ST_TYPE = { busy: 'warning', idle: 'success', leave: 'info', sick: 'info', absent: 'danger', off: 'info', off_hours: 'info' }
// 休息中的人（午休、还没到点）也能勾选、安排任务，只是不算在岗
const canPick = (r) => data.value?.can_add && ['busy', 'idle', 'off_hours'].includes(r.status)
function toggle(id, v) {
  picked.value = v ? [...picked.value, id] : picked.value.filter((x) => x !== id)
}
const title = computed(() => data.value
  ? t('duty.title', { shift: `${data.value.shift_date.slice(5)} ${t('shift.' + data.value.shift_kind)}` }) : '')

// 给勾选的人设置加班（这个班次）
const otOpen = ref(false)
const otPreset = ref(null)
function addOvertime() {
  otPreset.value = { mode: 'people', day: data.value.shift_date, shift_kind: data.value.shift_kind, worker_ids: [...picked.value] }
  otOpen.value = true
}
const hm = (iso) => dayjs(iso.slice(0, 16)).format('HH:mm') // 服务器给的是工厂本地时间
// 自定义上班时间：「07:00–12:00、14:00–17:00（12:00–14:00 休息）」
const hoursText = (h) => fullHours(h) + (breaks(h).length ? t('duty.breaks', { b: breaks(h).map(([a, b]) => `${a}–${b}`).join('、') }) : '')
// 不在上班时间：午休中几点回来 / 还没到点几点上班 / 今天已经下班
function offText(r) {
  if (!r.back_at) return t('duty.doneToday')
  const at = hm(r.back_at)
  return at === splitHours(r.hours)[0]?.[0] ? t('duty.startsAt', { t: at }) : t('duty.backAt', { t: at })
}

function addTask() {
  // 管理员默认派给这个班次的倒班班组；班长派给自己的班组
  const team = auth.hasOwnTeamHere ? auth.user.team_id : data.value.main_team_id
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
          <el-tag v-if="data.managers?.length" type="primary" effect="dark">{{ t('duty.managers', { n: data.counts.managers ?? 0 }) }}</el-tag>
          <el-tag type="primary">{{ t('duty.onDuty', { n: data.counts.on_duty }) }}</el-tag>
          <el-tag type="warning">{{ t('duty.busy', { n: data.counts.busy }) }}</el-tag>
          <el-tag type="success">{{ t('duty.idle', { n: data.counts.idle }) }}</el-tag>
          <el-tag v-if="data.counts.absent" type="info">{{ t('duty.absent', { n: data.counts.absent }) }}</el-tag>
          <el-tag v-if="data.counts.off_hours" type="info" effect="plain">{{ t('duty.offHours', { n: data.counts.off_hours }) }}</el-tag>
        </div>
        <div v-if="data.can_add" class="muted small">{{ t('duty.select') }}</div>
        <div v-if="!data.teams.some((x) => x.workers.length) && !data.top.length && !data.managers?.length" class="muted">{{ t('duty.none') }}</div>

        <el-alert v-if="data.managers_unscheduled?.length && (auth.isAdmin || auth.deptOk('worker.manage'))" type="warning" :closable="false" show-icon class="mgr-note"
                  :title="t('duty.mgrNoSched', { names: data.managers_unscheduled.join('、') })" />
        <!-- 最上面：管理人员（能给整个车间派活的人，按个人排班在班），2026-11-26 -->
        <section v-if="data.managers?.length" class="team top mgr">
          <h4>{{ t('duty.mgrTitle') }} <el-tag size="small" round>{{ data.managers.length }}</el-tag></h4>
          <div v-for="r in data.managers" :key="r.worker.id" :class="['person', `s-${r.status}`]">
            <el-checkbox v-if="canPick(r)" :model-value="picked.includes(r.worker.id)" @change="(v) => toggle(r.worker.id, v)" />
            <span v-else class="nocheck" />
            <WorkerAvatar :worker="r.worker" :size="40" />
            <div class="info">
              <div class="name">
                <b>{{ r.worker.name }}</b>
                <el-button v-if="auth.canWhy" link type="primary" size="small" class="why" :title="t('why.title')" @click="openWhy(r.worker)">{{ t('why.button') }}</el-button>
                <el-tag size="small" type="primary" effect="plain">{{ roleName(r.role_id) }}</el-tag>
                <el-tag v-if="r.team_id" size="small" effect="plain" type="info">{{ teamName(r.team_id) }}</el-tag>
                <el-tag :type="ST_TYPE[r.status]" size="small" effect="dark">{{ t('duty.st.' + r.status) }}</el-tag>
                <el-tag v-if="r.status === 'off_hours'" size="small" type="info" effect="plain">{{ offText(r) }}</el-tag>
                <el-tag v-if="r.overlap_until" size="small" type="primary" effect="plain" :title="t('duty.untilHint', { t: hm(r.overlap_until) })">{{ t('duty.untilT', { t: hm(r.overlap_until) }) }}</el-tag>
                <el-tag v-if="r.hours" size="small" effect="plain" class="hrs">⏱ {{ hoursText(r.hours) }}</el-tag>
                <el-tag v-if="r.overtime_until" size="small" type="warning" effect="plain">⏱ {{ t(r.overtime_prev ? 'ot.prevTag' : 'ot.untilTag', { t: hm(r.overtime_until) }) }}</el-tag>
              </div>
              <div v-for="task in r.tasks" :key="task.id" class="task" @click="emit('open-task', task.id)">
                <span :class="['dot', task.status]" />
                <span v-if="task.is_lead" class="lead">★</span>
                <span class="tt">{{ localText(task.content, task.source_lang).text }}</span>
              </div>
            </div>
          </div>
        </section>
        <!-- 上面一块：班长、副班长等「首页单独显示」的角色 -->
        <section v-if="data.top.length" class="team top">
          <h4>{{ topTitle }} <el-tag size="small" round>{{ data.top.length }}</el-tag></h4>
          <div v-for="r in data.top" :key="r.worker.id" :class="['person', `s-${r.status}`]">
            <el-checkbox v-if="canPick(r)" :model-value="picked.includes(r.worker.id)" @change="(v) => toggle(r.worker.id, v)" />
            <span v-else class="nocheck" />
            <WorkerAvatar :worker="r.worker" :size="40" />
            <div class="info">
              <div class="name">
                <b>{{ r.worker.name }}</b>
                <el-button v-if="auth.canWhy" link type="primary" size="small" class="why" :title="t('why.title')" @click="openWhy(r.worker)">{{ t('why.button') }}</el-button>
                <el-tag size="small" type="primary" effect="plain">{{ roleName(r.role_id) }}</el-tag>
                <el-tag size="small" effect="plain" type="info">{{ teamName(r.team_id) }}</el-tag>
                <el-tag :type="ST_TYPE[r.status]" size="small" effect="dark">{{ t('duty.st.' + r.status) }}</el-tag>
                <el-tag v-if="r.status === 'off_hours'" size="small" type="info" effect="plain">{{ offText(r) }}</el-tag>
                <el-tag v-if="r.overlap_until" size="small" type="primary" effect="plain" :title="t('duty.untilHint', { t: hm(r.overlap_until) })">{{ t('duty.untilT', { t: hm(r.overlap_until) }) }}</el-tag>
                <el-tag v-if="r.hours" size="small" effect="plain" class="hrs">⏱ {{ hoursText(r.hours) }}</el-tag>
                <el-tag v-if="r.overtime_until" size="small" type="warning" effect="plain">⏱ {{ t(r.overtime_prev ? 'ot.prevTag' : 'ot.untilTag', { t: hm(r.overtime_until) }) }}</el-tag>
              </div>
              <div v-for="task in r.tasks" :key="task.id" class="task" @click="emit('open-task', task.id)">
                <span :class="['dot', task.status]" />
                <span v-if="task.is_lead" class="lead">★</span>
                <span class="tt">{{ localText(task.content, task.source_lang).text }}</span>
              </div>
            </div>
          </div>
        </section>

        <section v-for="team in data.teams.filter((x) => x.workers.length)" :key="team.team_id" class="team">
          <h4>{{ teamName(team.team_id) }} <el-tag size="small" round>{{ team.workers.filter((w) => w.status === 'busy' || w.status === 'idle').length }}</el-tag></h4>
          <div v-for="r in team.workers" :key="r.worker.id" :class="['person', `s-${r.status}`]">
            <el-checkbox v-if="canPick(r)" :model-value="picked.includes(r.worker.id)" @change="(v) => toggle(r.worker.id, v)" />
            <span v-else class="nocheck" />
            <WorkerAvatar :worker="r.worker" :size="40" />
            <div class="info">
              <div class="name">
                <b>{{ r.worker.name }}</b>
                <el-button v-if="auth.canWhy" link type="primary" size="small" class="why" :title="t('why.title')" @click="openWhy(r.worker)">{{ t('why.button') }}</el-button>
                <el-tag :type="ST_TYPE[r.status]" size="small" effect="dark">{{ t('duty.st.' + r.status) }}</el-tag>
                <el-tag v-if="r.status === 'off_hours'" size="small" type="info" effect="plain">{{ offText(r) }}</el-tag>
                <el-tag v-if="r.overlap_until" size="small" type="primary" effect="plain" :title="t('duty.untilHint', { t: hm(r.overlap_until) })">{{ t('duty.untilT', { t: hm(r.overlap_until) }) }}</el-tag>
                <el-tag v-if="r.hours" size="small" effect="plain" class="hrs">⏱ {{ hoursText(r.hours) }}</el-tag>
                <el-tag v-if="r.support" size="small" effect="plain">{{ t('duty.support') }} · {{ teamName(r.worker.team_id) }}</el-tag>
                <el-tag v-if="r.overtime_until" size="small" type="warning" effect="plain">⏱ {{ t(r.overtime_prev ? 'ot.prevTag' : 'ot.untilTag', { t: hm(r.overtime_until) }) }}</el-tag>
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
      <div class="foot">
        <el-button :disabled="!picked.length" @click="addOvertime">{{ t('ot.add') }}</el-button>
        <el-button type="primary" :disabled="!picked.length" class="grow" @click="addTask">{{ t('duty.addTask', { n: picked.length }) }}</el-button>
      </div>
    </template>
    <OvertimeDialog v-model="otOpen" :preset="otPreset" @saved="load" />
    <WhyDialog v-model="why.open" type="worker" :id="why.id" :day="data?.shift_date || ''" :title="why.title" />
  </el-drawer>
</template>

<style scoped>
.foot { display: flex; gap: 8px; }
.mgr-note { margin-bottom: 8px; }
.why { font-size: 12px; padding: 0; height: auto; }
.foot .grow { flex: 1; }
.counts { display: flex; gap: 6px; flex-wrap: wrap; align-items: center; margin-bottom: 8px; }
.muted { color: #909399; }
.small { font-size: 12px; margin-bottom: 8px; }
.team.top { background: #f5f9ff; border-radius: 8px; padding: 2px 10px 6px; }
.team h4 { margin: 14px 0 6px; display: flex; gap: 6px; align-items: center; }
.person { display: flex; gap: 10px; align-items: flex-start; padding: 8px 0; border-bottom: 1px solid #f2f3f5; }
.person.s-leave, .person.s-sick, .person.s-absent, .person.s-off, .person.s-off_hours { opacity: .6; }
.hrs { color: #1d7a66; border-color: #8fd4c4; }
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
