<script setup>
// 员工的班组与排班（管理员）：变更记录 + 添加一次变更（从哪天起：哪个班组、跟班组排班还是个人循环）
// 例：每人休息日不同的一周排班 → 个人循环 7 天，从周一开始，休息那天点成「休」
import { computed, reactive, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { ElMessage, ElMessageBox } from 'element-plus'
import dayjs from 'dayjs'
import api from '../api'
import { localName } from '../i18n'
import { isNarrow } from '../format'
import { useAuth } from '../stores/auth'
import CycleEditor from './CycleEditor.vue'
import { shortEntry } from '../cycle'

const props = defineProps({ worker: { type: Object, default: null } })
const visible = defineModel({ type: Boolean })
const emit = defineEmits(['saved'])
const { t } = useI18n()
const auth = useAuth()
const rows = ref([])
const today = dayjs().format('YYYY-MM-DD')
const form = reactive({})
const monday = () => dayjs().add(((8 - dayjs().day()) % 7) || 7, 'day').format('YYYY-MM-DD') // 下周一

async function load() {
  rows.value = (await api.get(`/workers/${props.worker.id}/schedule`)).data
  // 新变更默认：从下周一起、保持当前班组、个人 7 天循环（周日休）
  const cur = currentRow.value
  Object.assign(form, {
    effective_from: monday(), team_id: cur?.team_id ?? props.worker.team_id, personal: !!cur?.pattern,
    cyc: { pattern: cur?.pattern ? [...cur.pattern] : ['day', 'day', 'day', 'day', 'day', 'day', 'off'],
      cycle_start: cur?.cycle_start || monday(), holiday_off: cur?.holiday_off ?? false },
    note: '',
  })
}
watch(visible, (v) => v && props.worker && load())

// 今天有效的那条
const currentRow = computed(() => [...rows.value].reverse().find((r) => r.effective_from <= today) || rows.value[0])
const teamName = (id) => (id ? localName(auth.teamById(id)) : t('ws.noTeam'))
const summary = (r) => (r.pattern
  ? `${t('ws.sumPersonal', { n: r.pattern.length })}：${r.pattern.map((k) => shortEntry(k, t)).join(' ')}`
  : t('ws.sumFollow', { team: teamName(r.team_id) }))

async function save() {
  rows.value = (await api.put(`/workers/${props.worker.id}/schedule`, {
    effective_from: form.effective_from, team_id: form.team_id, personal: form.personal, note: form.note,
    ...(form.personal ? { pattern: form.cyc.pattern, cycle_start: form.cyc.cycle_start, holiday_off: form.cyc.holiday_off } : {}),
  })).data
  ElMessage.success(t('common.saved'))
  emit('saved')
}
async function remove(r) {
  await ElMessageBox.confirm(`${r.effective_from} · ${summary(r)}`, t('common.delete'), { type: 'warning' })
  rows.value = (await api.delete(`/workers/${props.worker.id}/schedule/${r.effective_from}`)).data
  emit('saved')
}
</script>

<template>
  <el-dialog v-model="visible" :title="worker ? t('ws.title', { n: worker.name }) : ''" width="min(720px, 96vw)"
             :fullscreen="isNarrow()" append-to-body>
    <div class="hist">
      <div v-for="(r, i) in rows" :key="r.effective_from" :class="['h', { cur: r === currentRow }]">
        <div class="when">
          <b>{{ i === 0 && r.effective_from <= '2000-01-01' ? t('ws.since') : r.effective_from }}</b>
          <el-tag v-if="r === currentRow" size="small" type="success">{{ t('ws.current') }}</el-tag>
        </div>
        <div class="what">
          <span>{{ teamName(r.team_id) }}</span> · <span class="mono">{{ summary(r) }}</span>
          <div v-if="r.note" class="muted small">{{ r.note }}</div>
        </div>
        <el-button v-if="i > 0" link type="danger" size="small" @click="remove(r)">{{ t('common.delete') }}</el-button>
      </div>
    </div>

    <h4>{{ t('ws.add') }}</h4>
    <p class="muted small">{{ t('ws.hint') }}</p>
    <el-form label-width="auto">
      <el-form-item :label="t('ws.from')"><el-date-picker v-model="form.effective_from" value-format="YYYY-MM-DD" :clearable="false" /></el-form-item>
      <el-form-item :label="t('ws.team')">
        <el-select v-model="form.team_id" clearable :placeholder="t('ws.noTeam')" style="width: 180px">
          <el-option v-for="tm in auth.teams" :key="tm.id" :label="localName(tm)" :value="tm.id" />
        </el-select>
      </el-form-item>
      <el-form-item :label="t('schedule.cycleCol')">
        <el-radio-group v-model="form.personal">
          <el-radio :value="false">{{ t('ws.follow') }}</el-radio>
          <el-radio :value="true">{{ t('ws.personal') }}</el-radio>
        </el-radio-group>
      </el-form-item>
      <el-form-item v-if="form.personal" label=" "><CycleEditor v-model="form.cyc" /></el-form-item>
      <el-form-item :label="t('schedule.note')"><el-input v-model="form.note" maxlength="200" /></el-form-item>
    </el-form>
    <template #footer>
      <el-button @click="visible = false">{{ t('common.close') }}</el-button>
      <el-button type="primary" :disabled="!form.effective_from || (!form.personal && !form.team_id)" @click="save">{{ t('common.save') }}</el-button>
    </template>
  </el-dialog>
</template>

<style scoped>
.hist { display: flex; flex-direction: column; border: 1px solid #ebeef5; border-radius: 6px; }
.h { display: grid; grid-template-columns: 130px 1fr auto; gap: 8px; align-items: center; padding: 8px 10px; border-bottom: 1px solid #f2f3f5; }
.h:last-child { border-bottom: 0; }
.h.cur { background: #f0f9eb; }
.when { display: flex; gap: 6px; align-items: center; }
.mono { font-family: ui-monospace, Menlo, Consolas, monospace; }
.muted { color: #909399; }
.small { font-size: 12px; }
h4 { margin: 16px 0 4px; }
</style>
