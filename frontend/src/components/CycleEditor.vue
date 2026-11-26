<script setup>
// 循环排班编辑器（班组和个人排班共用）：几天一循环、每天上什么（点格子切换 白→中→夜→休）、循环第 1 天、节假日休息
import { computed, reactive, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import dayjs from 'dayjs'
import ShiftTag from './ShiftTag.vue'
import { isHours, shortEntry, splitHours, fullHours } from '../cycle'

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
  p[i] = NEXT[p[i]] || 'day' // 自定义时间段再点一下变回白班
  model.value.pattern = p
}

// ---- 自定义上班时间（例如 07:00-12:00、14:00-17:00）----
const hoursOpen = ref(false)
const hoursDay = ref(0)
const ranges = ref([])
const TIMES = Array.from({ length: 48 }, (_, i) => `${String(Math.floor(i / 2)).padStart(2, '0')}:${i % 2 ? '30' : '00'}`)
function openHours(i) {
  hoursDay.value = i
  const cur = model.value.pattern[i]
  ranges.value = isHours(cur) ? splitHours(cur).map(([a, b]) => ({ a, b }))
    : [{ a: '07:00', b: '12:00' }, { a: '14:00', b: '17:00' }]
  hoursOpen.value = true
}
const hoursText = computed(() => ranges.value.filter((r) => r.a && r.b).map((r) => `${r.a}-${r.b}`).join(','))
function applyHours(all) {
  if (!hoursText.value) return
  const p = [...model.value.pattern]
  if (all) p.forEach((k, j) => { if (k !== 'off') p[j] = hoursText.value }) // 所有上班的天都用这个时间
  else p[hoursDay.value] = hoursText.value
  model.value.pattern = p
  hoursOpen.value = false
}
function preset(name) {
  if (name === 'rot8') model.value.pattern = ['day', 'day', 'middle', 'middle', 'off', 'night', 'night', 'off']
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
    <el-dialog v-model="hoursOpen" :title="t('cyc.hoursTitle', { n: hoursDay + 1 })" width="min(420px, 94vw)" append-to-body>
      <p class="muted small">{{ t('cyc.hoursHint') }}</p>
      <div v-for="(r, j) in ranges" :key="j" class="rng">
        <el-select v-model="r.a" size="small" filterable style="width: 100px"><el-option v-for="x in TIMES" :key="x" :value="x" /></el-select>
        <span>–</span>
        <el-select v-model="r.b" size="small" filterable style="width: 100px"><el-option v-for="x in [...TIMES, '24:00']" :key="x" :value="x" /></el-select>
        <el-button v-if="ranges.length > 1" size="small" link type="danger" @click="ranges.splice(j, 1)">✕</el-button>
      </div>
      <el-button v-if="ranges.length < 4" size="small" @click="ranges.push({ a: '', b: '' })">+ {{ t('cyc.addRange') }}</el-button>
      <template #footer>
        <el-button @click="applyHours(true)">{{ t('cyc.applyAll') }}</el-button>
        <el-button type="primary" :disabled="!hoursText" @click="applyHours(false)">{{ t('common.save') }}</el-button>
      </template>
    </el-dialog>
    <div class="days">
      <div v-for="(k, i) in model.pattern" :key="i" class="dwrap">
        <button type="button" :class="['d', isHours(k) ? 'k-hours' : `k-${k}`]" :title="isHours(k) ? fullHours(k) : ''" @click="toggle(i)">
          <small>{{ t('cyc.nth', { n: i + 1 }) }}<template v-if="model.pattern.length % 7 === 0"> · {{ dayLabel(i) }}</template></small>
          <b :class="{ hrs: isHours(k) }">{{ shortEntry(k, t) }}</b>
        </button>
        <button type="button" class="clock" :title="t('cyc.setHours')" @click="openHours(i)">⏱</button>
      </div>
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
          <span v-if="isHours(p.k)" class="hrs-tag">{{ shortEntry(p.k, t) }}</span>
          <ShiftTag v-else :kind="p.k" />
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
.d.k-hours { background: #e8f8f5; border-color: #8fd4c4; color: #1d7a66; }
.d b.hrs { font-size: 11px; line-height: 1.25; text-align: center; }
.dwrap { position: relative; display: flex; }
.dwrap .d { flex: 1; min-height: 46px; }
.clock { position: absolute; top: 1px; right: 1px; border: 0; background: none; padding: 0 2px; font-size: 11px; cursor: pointer; opacity: .55; }
.clock:hover { opacity: 1; }
.rng { display: flex; gap: 6px; align-items: center; margin-bottom: 6px; }
.hrs-tag { font-size: 11px; color: #1d7a66; background: #e8f8f5; border-radius: 4px; padding: 1px 4px; white-space: nowrap; }
.pv { background: #f5f7fa; border-radius: 6px; padding: 6px 8px; }
.pvrow { display: grid; grid-template-columns: repeat(auto-fill, minmax(76px, 1fr)); gap: 4px; margin-top: 4px; }
.pvd { display: flex; flex-direction: column; align-items: center; gap: 2px; }
.pvd small { color: #606266; font-size: 11px; }
</style>
