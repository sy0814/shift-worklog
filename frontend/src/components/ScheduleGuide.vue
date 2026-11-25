<script setup>
// 「怎么改排班？」：所有改排班的地方归成四类（班组 / 个人 × 长期 / 某天），写明在哪改、谁优先。
// 排班页、出勤页顶部用；默认收起，展开状态记在本机。
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { useAuth } from '../stores/auth'

const { t } = useI18n()
const auth = useAuth()
const KEY = 'scheduleGuideOpen'
let saved = false
try { saved = localStorage.getItem(KEY) === '1' } catch { /* 无痕模式等 */ }
const open = ref(saved)
function toggle() {
  open.value = !open.value
  try { localStorage.setItem(KEY, open.value ? '1' : '0') } catch { /* ignore */ }
}

const cells = computed(() => [
  { key: 'teamLong', to: { path: '/schedule', query: { tab: 'teams' } }, ok: auth.deptOk('team.manage') },
  { key: 'teamDay', to: { path: '/schedule', query: { tab: 'calendar' } }, ok: auth.can('schedule.team_shift') },
  { key: 'personLong', to: { path: '/workers' }, ok: auth.deptOk('worker.manage') },
  { key: 'personDay', to: { path: '/attendance' }, ok: auth.can('attendance.edit') },
])
</script>

<template>
  <div class="sched-guide">
    <el-button link type="primary" size="small" @click="toggle">{{ t('sg.title') }} {{ open ? '▴' : '▾' }}</el-button>
    <div v-if="open" class="box">
      <div class="grid">
        <div v-for="c in cells" :key="c.key" class="cell">
          <b>{{ t(`sg.${c.key}.title`) }}</b>
          <div class="what">{{ t(`sg.${c.key}.what`) }}</div>
          <div class="where muted">
            {{ t(`sg.${c.key}.where`) }}
            <router-link v-if="c.ok" :to="c.to" class="go">{{ t('sg.go') }} →</router-link>
          </div>
        </div>
      </div>
      <div class="order">{{ t('sg.order') }}</div>
    </div>
  </div>
</template>

<style scoped>
.sched-guide { margin: 4px 0 8px; }
.box { margin-top: 4px; padding: 10px 12px; border-radius: 6px; background: var(--el-fill-color-light); }
.grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 8px; }
@media (max-width: 640px) { .grid { grid-template-columns: 1fr; } }
.cell { padding: 8px 10px; border-radius: 6px; background: var(--el-bg-color); border: 1px solid var(--el-border-color-lighter); }
.what { margin: 2px 0; font-size: 13px; }
.where { font-size: 12px; }
.go { margin-left: 6px; color: var(--el-color-primary); text-decoration: none; white-space: nowrap; }
.order { margin-top: 8px; font-size: 13px; }
</style>
