// 循环里每天的写法：day / middle / night / off，或自定义上班时间 "07:00-12:00,14:00-17:00"
export const KINDS = ['day', 'middle', 'night', 'off']
export const isHours = (k) => !!k && !KINDS.includes(k)

/** 时间段 → [[ '07:00', '12:00' ], [ '14:00', '17:00' ]] */
export function splitHours(k) {
  return isHours(k) ? k.split(',').map((p) => p.trim().split('-')) : []
}

/** 简短显示：班次用「白 / 中 / 夜 / 休」；时间段用「7-12 14-17」（整点省略分钟） */
export function shortEntry(k, t) {
  if (!isHours(k)) return t('cyc.short.' + k)
  const hm = (s) => (s.endsWith(':00') ? String(Number(s.slice(0, 2))) : s.replace(/^0/, ''))
  return splitHours(k).map(([a, b]) => `${hm(a)}-${hm(b)}`).join(' ')
}

/** 完整显示：07:00–12:00、14:00–17:00 */
export function fullHours(k) {
  return splitHours(k).map(([a, b]) => `${a}–${b}`).join('、')
}
