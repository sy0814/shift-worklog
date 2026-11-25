// 离线发件箱：新建任务、补充图片、开始 / 完成任务、班次日志先写进 IndexedDB，再尝试上传（按点的先后顺序）。
// 网络不通时留在本地，联网后自动重试；服务器按 client_id 去重，重复提交不会产生重复数据。
import { openDB } from 'idb'
import { toRaw } from 'vue'

const dbp = openDB('workrecord', 1, {
  upgrade(db) {
    db.createObjectStore('outbox', { keyPath: 'key' })
  },
})

export const uuid = () =>
  crypto.randomUUID
    ? crypto.randomUUID()
    : 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, (c) => {
        const r = (Math.random() * 16) | 0
        return (c === 'x' ? r : (r & 0x3) | 0x8).toString(16)
      })

// Vue 的响应式代理不能存进 IndexedDB（DataCloneError），先转成普通对象
function plain(entry) {
  const e = toRaw(entry)
  return {
    ...e,
    task: e.task ? JSON.parse(JSON.stringify(toRaw(e.task))) : null,
    log: e.log ? JSON.parse(JSON.stringify(toRaw(e.log))) : null,
    photos: toRaw(e.photos || []).map((p) => ({ ...toRaw(p), blob: toRaw(p).blob })),
  }
}

export async function putEntry(entry) {
  return (await dbp).put('outbox', plain(entry))
}
export async function getEntries(userId) {
  const all = await (await dbp).getAll('outbox')
  return all.filter((e) => e.user_id === userId).sort((a, b) => a.saved_at - b.saved_at)
}
export async function deleteEntry(key) {
  return (await dbp).delete('outbox', key)
}

/** 网络层面的失败（没有响应、网关超时）→ 留着以后重试；其他错误是服务器拒绝，需要人处理 */
export const isNetworkError = (err) => !err.response || [502, 503, 504].includes(err.response.status)

/** 联网时把首页上未完成任务的详情先读一遍，Service Worker 会缓存下来；
 *  走到 Wi-Fi 死角时也能打开这些任务点「开始 / 完成」。每条任务 10 分钟内只读一次。 */
const warmed = new Map()
export async function warmTasks(api, ids) {
  if (!navigator.serviceWorker?.controller) return
  const now = Date.now()
  for (const id of ids.slice(0, 40)) {
    if (now - (warmed.get(id) || 0) < 600_000) continue
    warmed.set(id, now)
    try {
      const r = await api.get(`/tasks/${id}`, { silent: true })
      if (r.headers['x-from-cache']) return // 已经断网了
    } catch {
      return
    }
  }
}
