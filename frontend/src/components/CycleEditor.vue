<script setup>
// 循环排班编辑器（班组和个人排班共用）：几天一循环、每天上什么（点格子切换 白→中→夜→休）、循环第 1 天、节假日休息
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import dayjs from 'dayjs'
import ShiftTag from './ShiftTag.vue'

const model = defineModel({ type: Object, required: true }) // { pattern: [], cycle_start: 'YYYY-MM-DD', holiday_off: bool }
const { t, locale } = useI18n()
const NEXT = { day: 'middle', middle: 'night', night: 'off', off: 'day' }
const MAX = 62

const len = computed({
  get: () => model.value.pattern.length,
  set: (n) => {
    n = Math.max(1, Math.min(MAX, n || 1))
    const p = model.value.pattern.slice(0, n)
    while (p.length < n) p.push('off')
    model.value.pattern = p
  },
})
function toggle(i) {
  const p = [...model.value.pattern]
  p[i] = NEXT[p[i]]
  model.value.pattern = p
}
function preset(name) {
  if (name === 'rot8') model.value.pattern = ['day', 'day', 'middle', 'middle', 'night', 'night', 'off', 'off']
  if (name === 'week5') {
    model.value.pattern = ['day', 'day', 'day', 'day', 'day', 'off', 'off']
    model.value.holiday_off = true
    const d = dayjs(model.value.cycle_start || undefined)
    model.value.cycle_start = d.subtract((d.day() + 6) % 7, 'day').format('YYYY-MM-DD') // 从周一开始
  }
  if (name === 'week6') {
    model.value.pattern = ['day', 'day', 'day', 'day', 'day', 'day', 'off']
    const d = dayjs(model.value.cycle_start || undefined)
    model.value.cycle_start = d.subtract((d.day() + 6) % 7, 'day').format('YYYY-MM-DD')
  }
}
const WD = { zh: '日一二三四五六', sr: ['ned', 'pon', 'uto', 'sre', 'čet', 'pet', 'sub'], en: ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'] }
const wd = (d) => WD[locale.value][d.day()]
// 第 i 天对应的星期（7 天一循环时最有用）
const dayLabel = (i) => {
  if (!model.value.cycle_start) return ''
  return wd(dayjs(model.value.cycle_start).add(i, 'day'))
}
// 接下来 14 天的预览（不含节假日和班组调班，保存后在排班日历里看最终结果）
const preview = computed(() => {
  const { pattern, cycle_start: s } = model.value
  if (!pattern.length || !s) return []
  const start = dayjs(s)
  const today = dayjs().startOf('day')
  return Array.from({ length: 14 }, (_, i) => {
    const d = today.add(i, 'day')
    const n = ((d.diff(start, 'day') % pattern.length) + pattern.length) % pattern.length
    return { d: d.format('MM-DD'), w: wd(d), k: pattern[n] }
  })
})
</script>

<template>
  <div class="cyc">
    <div class="row">
      <span class="lbl">{{ t('cyc.presets') }}</span>
      <el-button size="small" @click="preset('rot8')">{{ t('cyc.rot8') }}</el-button>
      <el-button size="small" @click="preset('week5')">{{ t('cyc.week5') }}</el-button>
      <el-button size="small" @click="preset('week6')">{{ t('cyc.week6') }}</el-button>
    </div>
    <div class="row">
      <span class="lbl">{{ t('cyc.len') }}</span>
      <el-input-number v-model="len" :min="1" :max="MAX" size="small" style="width: 110px" />
      <span class="lbl">{{ t('cyc.start') }}</span>
      <el-date-picker v-model="model.cycle_start" value-format="YYYY-MM-DD" :clearable="false" size="small" style="width: 150px" />
    </div>
    <div class="muted small">{{ t('cyc.clickHint') }}</div>
    <div class="days">
      <button v-for="(k, i) in model.pattern" :key="i" type="button" :class="['d', `k-${k}`]" @click="toggle(i)">
        <small>{{ t('cyc.nth', { n: i + 1 }) }}<template v-if="model.pattern.length % 7 === 0"> · {{ dayLabel(i) }}</template></small>
        <b>{{ t(`cyc.short.${k}`) }}</b>
      </button>
    </div>
    <div class="row">
      <el-switch v-model="model.holiday_off" size="small" />
      <span>{{ t('cyc.holidayOff') }}</span>
    </div>
    <div v-if="preview.length" class="pv">
      <span class="muted small">{{ t('cyc.preview') }}</span>
      <div class="pvrow">
        <div v-for="p in preview" :key="p.d" class="pvd">
          <small>{{ p.d }} {{ p.w }}</small>
          <ShiftTag :kind="p.k" />
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.cyc { display: flex; flex-direction: column; gap: 8px; width: 100%; }
.row { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }
.lbl { color: #606266; font-size: 13px; }
.muted { color: #909399; }
.small { font-size: 12px; }
.days { display: grid; grid-template-columns: repeat(auto-fill, minmax(62px, 1fr)); gap: 6px; }
.d { display: flex; flex-direction: column; align-items: center; gap: 2px; padding: 4px 2px; border-radius: 6px; border: 1px solid #dcdfe6;
  background: #fff; cursor: pointer; font-family: inherit; user-select: none; }
.d small { color: #909399; font-size: 11px; white-space: nowrap; }
.d b { font-size: 15px; }
.d.k-day { background: #fdf6ec; border-color: #f3d19e; color: #b88230; }
.d.k-middle { background: #ecf5ff; border-color: #a0cfff; color: #337ecc; }
.d.k-night { background: #f2ecfa; border-color: #c8b4e6; color: #5b3e8c; }
.d.k-off { background: #f4f4f5; color: #909399; }
.pv { background: #f5f7fa; border-radius: 6px; padding: 6px 8px; }
.pvrow { display: grid; grid-template-columns: repeat(auto-fill, minmax(76px, 1fr)); gap: 4px; margin-top: 4px; }
.pvd { display: flex; flex-direction: column; align-items: center; gap: 2px; }
.pvd small { color: #606266; font-size: 11px; }
</style>
