<script setup>
// 子项目分给谁：班组（班长再安排人），或具体的人（显示他下一个班；休息的人标出来，方便改派）
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { localName } from '../i18n'
import { useAuth } from '../stores/auth'

const model = defineModel({ type: Object, required: true }) // { mode: 'team' | 'person', team_id, worker_id }
const props = defineProps({
  workers: { type: Array, default: () => [] },
  slots: { type: Object, default: () => ({}) }, // worker_id → { next_date, next_kind, on_now }
  allowDefault: { type: Boolean, default: false }, // 定期巡查的小项目：可以不指定（跟巡查这次派给的班组）
  perm: { type: String, default: 'project.manage' }, // 能分给哪些班组按这个权限算
})
const { t } = useI18n()
const auth = useAuth()

const teams = computed(() => auth.teams.filter((tm) => auth.teamOk(props.perm, tm.id)))
const groups = computed(() => teams.value.map((tm) => ({
  label: localName(tm), list: props.workers.filter((w) => w.team_id === tm.id),
})).filter((g) => g.list.length))
function slotText(id) {
  const s = props.slots[id]
  if (!s || !s.next_date) return t('proj.noShift')
  if (s.on_now) return t('proj.onNow')
  return `${s.next_date.slice(5)} ${t('shift.' + s.next_kind)}`
}
const picked = computed(() => props.slots[model.value.worker_id])
</script>

<template>
  <div class="tp">
    <el-radio-group v-model="model.mode" size="small">
      <el-radio-button v-if="allowDefault" value="default">{{ t('proj.toDefault') }}</el-radio-button>
      <el-radio-button value="team">{{ t('proj.toTeam') }}</el-radio-button>
      <el-radio-button value="person">{{ t('proj.toPerson') }}</el-radio-button>
    </el-radio-group>
    <template v-if="model.mode === 'default'" />
    <el-select v-else-if="model.mode === 'team'" v-model="model.team_id" size="small" class="sel" :placeholder="t('proj.pickTeam')">
      <el-option v-for="tm in teams" :key="tm.id" :label="localName(tm)" :value="tm.id" />
    </el-select>
    <el-select v-else v-model="model.worker_id" size="small" filterable class="sel" :placeholder="t('proj.pickPerson')">
      <el-option-group v-for="g in groups" :key="g.label" :label="g.label">
        <el-option v-for="w in g.list" :key="w.id" :label="w.name" :value="w.id">
          <span>{{ w.name }}</span>
          <span :class="['slot', { now: slots[w.id]?.on_now }]">{{ slotText(w.id) }}</span>
        </el-option>
      </el-option-group>
    </el-select>
    <span v-if="model.mode === 'person' && model.worker_id && picked && !picked.on_now && !allowDefault" class="warn">
      ⚠ {{ t('proj.notNow', { s: slotText(model.worker_id) }) }}
    </span>
  </div>
</template>

<style scoped>
.tp { display: flex; gap: 6px; align-items: center; flex-wrap: wrap; }
.sel { width: 190px; }
.slot { float: right; color: #909399; font-size: 12px; margin-left: 12px; }
.slot.now { color: #67c23a; }
.warn { color: #e6a23c; font-size: 12px; }
</style>
