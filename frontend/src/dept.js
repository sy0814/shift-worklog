// 当前车间（只有一个车间时用不到）：存在本机，所有请求带 X-Department 头。
// 服务器只对能切换车间的人（系统管理员、看任务范围为「全厂」的角色）认这个头，其他人永远是自己的车间。
export function getDept() {
  try {
    const v = Number(localStorage.getItem('dept'))
    return Number.isFinite(v) && v > 0 ? v : null
  } catch {
    return null
  }
}

export function setDeptId(id) {
  try {
    if (id) localStorage.setItem('dept', String(id))
    else localStorage.removeItem('dept')
  } catch { /* 存不了就只在这一次有效 */ }
}
