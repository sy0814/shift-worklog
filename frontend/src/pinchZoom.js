// 看大图（Element Plus 的图片预览）支持两指缩放：它自己只支持滚轮、按钮和单指拖动。
// 两指张开 / 捏合时，每变化 15% 给预览发一次滚轮事件（它的滚轮 = 放大 / 缩小一档），单指照样拖动。
const STEP = 1.15

function dist(t) {
  return Math.hypot(t[0].pageX - t[1].pageX, t[0].pageY - t[1].pageY)
}

export function installPinchZoom() {
  let wrapper = null
  let last = 0
  document.addEventListener('touchstart', (e) => {
    const w = e.target.closest?.('.el-image-viewer__wrapper')
    if (!w || e.touches.length !== 2) return
    wrapper = w
    last = dist(e.touches)
    e.preventDefault()
  }, { passive: false, capture: true })
  document.addEventListener('touchmove', (e) => {
    if (!wrapper || e.touches.length !== 2) return
    e.preventDefault() // 不让整页跟着缩放
    const d = dist(e.touches)
    const ratio = d / last
    if (ratio > STEP || ratio < 1 / STEP) {
      wrapper.dispatchEvent(new WheelEvent('wheel', { deltaY: ratio > 1 ? -100 : 100, bubbles: true, cancelable: true }))
      last = d
    }
  }, { passive: false, capture: true })
  const end = (e) => { if (e.touches.length < 2) wrapper = null }
  document.addEventListener('touchend', end, { capture: true })
  document.addEventListener('touchcancel', end, { capture: true })
}
