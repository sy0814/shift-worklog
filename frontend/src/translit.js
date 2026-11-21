// 塞尔维亚语西里尔字母 → 拉丁字母（用于 Element Plus 自带的 sr 文案）
const MAP = {
  А: 'A', Б: 'B', В: 'V', Г: 'G', Д: 'D', Ђ: 'Đ', Е: 'E', Ж: 'Ž', З: 'Z', И: 'I', Ј: 'J', К: 'K',
  Л: 'L', Љ: 'Lj', М: 'M', Н: 'N', Њ: 'Nj', О: 'O', П: 'P', Р: 'R', С: 'S', Т: 'T', Ћ: 'Ć', У: 'U',
  Ф: 'F', Х: 'H', Ц: 'C', Ч: 'Č', Џ: 'Dž', Ш: 'Š',
}
for (const [k, v] of Object.entries({ ...MAP })) MAP[k.toLowerCase()] = v.toLowerCase()

export const toLatin = (s) => s.replace(/[Ѐ-ӿ]/g, (c) => MAP[c] ?? c)

export function deepLatin(obj) {
  if (typeof obj === 'string') return toLatin(obj)
  if (Array.isArray(obj)) return obj.map(deepLatin)
  if (obj && typeof obj === 'object') {
    return Object.fromEntries(Object.entries(obj).map(([k, v]) => [k, deepLatin(v)]))
  }
  return obj
}
