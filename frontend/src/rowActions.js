// 表格「操作」列：电脑上所有按钮排一行；手机上只放前 keep 个，其余收进「⋯」。
// 列宽按当前语言的按钮文字算（塞语最长），保证不换行。用法见 components/RowActions.vue。
import { computed, onMounted, onUnmounted, ref } from 'vue'

const narrow = ref(typeof window !== 'undefined' && window.innerWidth < 768)
let listeners = 0
const onResize = () => { narrow.value = window.innerWidth < 768 }

/** 是不是手机宽度（随窗口变化） */
export function useNarrow() {
  onMounted(() => { if (listeners++ === 0) window.addEventListener('resize', onResize) })
  onUnmounted(() => { if (--listeners === 0) window.removeEventListener('resize', onResize) })
  return narrow
}

let ctx
function textWidth(s, size = 14, bold = false) {
  ctx = ctx || document.createElement('canvas').getContext('2d')
  ctx.font = `${bold ? 'bold ' : ''}${size}px -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif`
  return ctx.measureText(s || '').width
}

/** 普通列的宽度：表头（粗体 12px）和每行内容（13px）取最宽的，不换行、不被截断。
 *  texts = 这一列可能出现的文字；extra = 内容另外占的宽度（例如标签的内边距） */
export function colWidth(header, texts = [], extra = 0) {
  const h = textWidth(header, 12, true) * 1.12
  const c = Math.max(0, ...texts.map((x) => textWidth(String(x ?? ''), 13) * 1.12 + extra))
  return Math.ceil(Math.max(h, c) + 26) // 单元格左右内边距 + 边框
}

/** 一排标签（size="small"）的宽度 */
export function tagsWidth(labels) {
  return labels.filter(Boolean).reduce((s, l) => s + textWidth(l, 12) * 1.12 + 18, 0) + 4 * Math.max(0, labels.length - 1)
}

const btnWidth = (l) => textWidth(l) * 1.12 + 6
const NARROW_MAX = 150 // 手机上直接显示的按钮一共不超过这么宽（剩下的收进「⋯」），免得操作列占掉整屏

/** 手机上直接显示几个按钮：最多 keep 个，且加起来不超过 NARROW_MAX（至少 1 个） */
export function narrowKeep(labels, keep = 2) {
  let w = 0
  let n = 0
  for (const l of labels.slice(0, keep)) {
    w += btnWidth(l) + (n ? GAP : 0)
    if (n && w > NARROW_MAX) break
    n += 1
  }
  return labels.length > n ? Math.max(1, n) : labels.length
}

export const MORE_WIDTH = 28 // 「⋯」按钮
const GAP = 12 // 按钮之间
const PAD = 24 // 单元格左右内边距

/** labels：这一列可能出现的所有按钮文字（函数，语言变了会重算）；keep：手机上直接显示几个；
 *  collapse=false：手机上也不收（例如一排状态标签）；max：电脑上最多直接显示几个（函数，可随窗口宽度变） */
export function useActionsWidth(labels, keep = 2, collapse = true, max = null) {
  const n = useNarrow()
  return computed(() => {
    const all = labels().filter(Boolean)
    const m = max ? max() : all.length
    const shown = n.value && collapse ? all.slice(0, narrowKeep(all, keep)) : all.slice(0, m)
    // 文字宽按 1.12 倍算（各系统字体宽窄不一，Windows 的微软雅黑偏宽），每个按钮再加 6px
    const w = shown.reduce((s, l) => s + btnWidth(l), 0) + GAP * Math.max(0, shown.length - 1) + PAD
    return Math.ceil(w + (shown.length < all.length ? GAP + MORE_WIDTH : 0))
  })
}
