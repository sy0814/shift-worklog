// 离线发件箱：新建任务、补充图片先写进 IndexedDB，再尝试上传。
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
    photos: toRaw(e.photos).map((p) => ({ ...toRaw(p), blob: toRaw(p).blob })),
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
