<script setup>
// 「为什么？」：某人某天 / 某班组某天的排班是怎么得出来的（GET /api/explain/...）。
// 每一步按判定顺序列出，后面的覆盖前面的；带「谁、什么时候设的、备注」。步骤 code 的含义见 backend/app/explain.py
import { ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import api from '../api'
import { fmtFull } from '../format'
import { useAuth } from '../stores/auth'
import { fullHours, isHours } from '../cycle'
import dayjs from 'dayjs'
import ShiftTag from './ShiftTag.vue'

const props = defineProps({
  type: { type: String, required: true }, // worker / team
  id: { type: Number, required: true },
  day: { type: String, required: true },
  hide: { type: Array, default: () => [] }, // 不显示「去修改」的步骤（已经在那个地方了，例如出勤格子弹窗里的 attendance）
})
const emit = defineEmits(['navigate']) // 点了「去修改」：外面的弹窗关掉
const { t } = useI18n()
const auth = useAuth()
const data = ref(null)
const loading = ref(false)
const failed = ref(false)

async function load() {
  if (!props.id || !props.day) return
  loading.value = true
  failed.value = false
  try {
    data.value = (await api.get(`/explain/${props.type}/${props.id}`, { params: { day: props.day } })).data
  } catch {
    failed.value = true
  } finally {
    loading.value = false
  }
}
watch(() => [props.type, props.id, props.day], load, { immediate: true })
defineExpose({ load })

const team = (id) => auth.teamLabel(id) || `#${id}`
const entry = (e) => (isHours(e) ? fullHours(e) : t('shift.' + e))
const shift = (k) => t('shift.' + k)
const d = (s) => (s ? String(s).slice(0, 10) : '…')

function text(s) {
  switch (s.code) {
    case 'membership':
      if (s.team_id == null && !s.personal) return t('why.noTeam')
      return t(s.always ? 'why.membershipAlways' : 'why.membership', { team: team(s.team_id), since: d(s.since) })
        + (s.personal ? t('why.personalSuffix') : '')
    case 'personal_cycle': return t('why.personal')
    case 'team_cycle': return t(s.manual ? 'why.teamManual' : 'why.teamCycle', { team: team(s.team_id) })
    case 'inactive': return t('why.inactive', { team: team(s.team_id), from: d(s.active_from), to: s.active_to ? d(s.active_to) : '' })
    case 'cycle': return t('why.cycle', { pos: s.pos, len: s.length, start: d(s.start), entry: entry(s.entry) })
    case 'holiday': return t(s.name ? 'why.holidayNamed' : 'why.holiday', { name: s.name, was: entry(s.was) })
    case 'workday': return t('why.workday', { entry: entry(s.entry) })
    case 'team_override': return t('why.override', { team: team(s.team_id), entry: entry(s.entry), planned: entry(s.planned) })
    case 'hours_kind': return t('why.hoursKind', { hours: fullHours(s.hours), kind: shift(s.kind) })
    case 'member_shift': return t('why.memberShift', { team: team(s.team_id), kind: shift(s.kind),
      names: (s.workers || []).map((w) => w.name).join(t('why.sep')) || '—' })
    case 'member_ignored': return t('why.memberIgnored', { team: team(s.team_id), kind: shift(s.kind),
      names: (s.workers || []).map((w) => w.name).join(t('why.sep')) || '—' })
    case 'attendance': {
      let what = t('att.st.' + s.status)
      if (s.status === 'present') {
        if (s.shift_kind) what += ' · ' + shift(s.shift_kind)
        if (s.team_id) what += ' · ' + t('why.coverTeam', { team: team(s.team_id) })
      }
      return t('why.attendance', { src: t('why.src.' + (s.source === 'import' ? 'import' : 'manual')), what })
    }
    case 'cover': return s.kind ? t('why.cover', { team: team(s.team_id), kind: shift(s.kind) }) : t('why.coverNone', { team: team(s.team_id) })
    case 'hours_dropped': return t('why.hoursDropped', { hours: fullHours(s.hours) })
    case 'group': {
      if (!s.main) return t('why.groupNone', { kind: shift(s.kind) })
      if (s.alone) return t('why.groupAlone', { kind: shift(s.kind), main: team(s.main) })
      if (s.team_ids.length === 1) return t('why.groupSingle', { kind: shift(s.kind), main: team(s.main) })
      return t('why.group', { kind: shift(s.kind), main: team(s.main), teams: s.team_ids.map(team).join(' + ') })
    }
    case 'overtime': return t('why.overtime', { until: dayjs(s.until).format('MM-DD HH:mm'), h: s.hours })
      + (s.whole_team ? t('why.wholeTeam') : '')
    default: return s.code
  }
}
// 「去修改」：这一步是在哪里设的，直接打开那个地方（没权限的不显示）。目标页面按 query 打开对应的弹窗
function link(s) {
  if (props.hide.includes(s.code)) return null
  const wid = props.type === 'worker' ? props.id : null
  const go = (path, query, label) => ({ to: { path, query }, label })
  switch (s.code) {
    case 'membership': // 个人循环也在这里改（personal_cycle 那一步不重复给链接）
      return wid && auth.deptOk('worker.manage') ? go('/workers', { schedule: wid }, 'person') : null
    case 'team_cycle': case 'inactive':
      return auth.deptOk('team.manage') ? go('/schedule', { tab: 'teams', team: s.team_id }, 'team') : null
    case 'holiday': case 'workday':
      return auth.isAdmin ? go('/schedule', { tab: 'holidays' }, 'holiday') : null
    case 'team_override':
      return auth.teamOk('schedule.team_shift', s.team_id) ? go('/schedule', { tab: 'calendar', shift: s.team_id, day: props.day }, 'override') : null
    case 'attendance':
      return wid && auth.can('attendance.edit') ? go('/attendance', { worker: wid, day: props.day }, 'attendance') : null
    case 'member_shift': case 'member_ignored':
      return auth.can('attendance.edit') ? go('/attendance', { team: s.team_id, month: props.day.slice(0, 7) }, 'members') : null
    case 'overtime':
      return wid && auth.can('overtime.edit') ? go('/attendance', { worker: wid, day: props.day }, 'overtime') : null
    default: return null
  }
}
// 会改变结果的步骤标颜色（覆盖了前面的）
const STRONG = new Set(['team_override', 'attendance', 'holiday', 'workday', 'inactive', 'member_shift', 'cover', 'personal_cycle'])
</script>

<template>
  <div v-loading="loading" class="why">
    <div v-if="failed" class="muted">{{ t('why.failed') }}</div>
    <template v-else-if="data">
      <div class="result">
        <b>{{ t('why.result') }}</b>
        <template v-if="type === 'team'">
          <ShiftTag :kind="data.result.kind" />
          <span v-if="isHours(data.result.entry)" class="muted">⏱ {{ fullHours(data.result.entry) }}</span>
        </template>
        <template v-else-if="data.result.status">
          <el-tag v-if="data.result.status !== 'present'" type="info">{{ t('att.st.' + data.result.status) }}</el-tag>
          <ShiftTag v-else :kind="data.result.shift_kind" />
          <span v-if="data.result.hours" class="muted">⏱ {{ fullHours(data.result.hours) }}</span>
          <span v-if="data.result.team_id" class="muted">· {{ team(data.result.team_id) }}</span>
        </template>
        <span v-else class="muted">{{ t('why.noTeam') }}</span>
      </div>
      <ol class="steps">
        <li v-for="(s, i) in data.steps" :key="i" :class="{ strong: STRONG.has(s.code) }">
          <div>{{ text(s) }}<router-link v-if="link(s)" :to="link(s).to" class="fix" @click="emit('navigate')">{{ t('why.fix.' + link(s).label) }} →</router-link></div>
          <div v-if="s.by_name || s.note" class="meta muted">
            <span v-if="s.by_name">{{ t('why.by', { name: $pn(s.by_name), at: fmtFull(s.at) }) }}</span>
            <span v-if="s.note">{{ t('why.note', { note: s.note }) }}</span>
          </div>
        </li>
      </ol>
      <div class="muted small">{{ t('why.hint') }}</div>
    </template>
  </div>
</template>

<style scoped>
.why { min-height: 60px; }
.result { display: flex; flex-wrap: wrap; align-items: center; gap: 6px; margin-bottom: 8px; }
.steps { margin: 0 0 8px; padding-left: 22px; }
.steps li { margin: 4px 0; line-height: 1.5; }
.steps li.strong { color: var(--el-color-warning-dark-2); }
.fix { margin-left: 8px; font-size: 12px; color: var(--el-color-primary); text-decoration: none; white-space: nowrap; }
.meta { font-size: 12px; display: flex; flex-wrap: wrap; gap: 0 12px; }
.small { font-size: 12px; }
</style>
