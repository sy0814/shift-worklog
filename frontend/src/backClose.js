// 安卓 App（以及装到主屏幕的 PWA）里按「返回」：先关最上面的弹窗 / 抽屉（任务详情、项目详情……），
// 没有打开的才回上一页 / 退出。做法：弹窗打开时往浏览器历史里压一条，返回键（Capacitor 是 webView.goBack）
// 把它弹出来 → 我们给最上面的弹窗发 Esc（Element Plus 的弹窗、抽屉、确认框都按 Esc 关闭）。
// 用户自己点 × 关掉弹窗时，把压进去的那条历史退掉，免得要多按一次返回。

const isOpen = (el) => getComputedStyle(el).display !== 'none'

function openOverlays() {
  return [...document.querySelectorAll('.el-overlay')].filter(isOpen)
}

function topOverlay() {
  const list = openOverlays()
  return list.sort((a, b) => (Number(getComputedStyle(b).zIndex) || 0) - (Number(getComputedStyle(a).zIndex) || 0))[0]
}

function sendEscape(overlay) {
  const target = overlay.querySelector('.el-dialog, .el-drawer, .el-message-box') || overlay
  const ev = { key: 'Escape', code: 'Escape', keyCode: 27, bubbles: true, cancelable: true }
  target.dispatchEvent(new KeyboardEvent('keydown', ev))
}

export function installBackClose() {
  let pushed = 0 // 为打开的弹窗压进历史的条数
  let ignorePop = 0 // 我们自己调 history.back() 引起的 popstate，不处理
  let count = 0

  const sync = () => {
    const n = openOverlays().length
    if (n > count) {
      for (let i = count; i < n; i++) { history.pushState({ ...(history.state || {}), overlay: true }, ''); pushed++ }
    } else if (n < count && pushed > n) {
      // 弹窗是点 × / 保存关掉的：把多压的历史退掉
      const extra = pushed - n
      pushed = n
      ignorePop += extra
      history.go(-extra)
    }
    count = n
  }
  let queued = false
  const schedule = () => { if (!queued) { queued = true; setTimeout(() => { queued = false; sync() }, 50) } }
  new MutationObserver(schedule).observe(document.body, { childList: true, subtree: true, attributes: true, attributeFilter: ['style', 'class'] })

  window.addEventListener('popstate', () => {
    if (ignorePop > 0) { ignorePop--; return }
    if (pushed > 0) {
      pushed--
      const top = topOverlay()
      if (top) {
        sendEscape(top)
        // 有的弹窗不允许按 Esc 关（例如正在填的表单设了不能关）：还开着就把历史补回去，下次返回再试
        setTimeout(() => { if (isOpen(top)) { history.pushState({ ...(history.state || {}), overlay: true }, ''); pushed++ } else count = openOverlays().length }, 400)
      }
    }
  })
}
