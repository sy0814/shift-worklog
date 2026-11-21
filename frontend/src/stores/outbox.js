import { defineStore } from 'pinia'
import api from '../api'
import { deleteEntry, getEntries, isNetworkError, putEntry, uuid } from '../offline'
import { useAuth } from './auth'

export const useOutbox = defineStore('outbox', {
  state: () => ({ entries: [], syncing: false, online: navigator.onLine, lastSyncedTaskIds: [] }),
  getters: {
    count: (s) => s.entries.length,
  },
  actions: {
    async refresh() {
      const auth = useAuth()
      this.entries = auth.user ? await getEntries(auth.user.id) : []
    },

    /** 新建任务（含图片）：先存本地再同步。返回同步后的任务；离线时返回 null */
    async submitTask(body, photos) {
      const auth = useAuth()
      const entry = {
        key: body.client_id, user_id: auth.user.id, type: 'task', task: body, task_id: null,
        photos, saved_at: Date.now(), error: null,
      }
      await putEntry(entry)
      await this.refresh()
      return this.syncEntry(entry)
    },

    /** 给已有任务补充图片 */
    async submitPhotos(taskId, photos) {
      const auth = useAuth()
      const entry = {
        key: uuid(), user_id: auth.user.id, type: 'photos', task: null, task_id: taskId,
        photos, saved_at: Date.now(), error: null,
      }
      await putEntry(entry)
      await this.refresh()
      return this.syncEntry(entry)
    },

    /** 同步一条。成功返回任务对象；网络失败返回 null（保留在本地）；服务器拒绝则记录错误并抛出 */
    async syncEntry(entry) {
      try {
        let task = null
        if (entry.task_id == null) {
          task = (await api.post('/tasks', entry.task, { silent: true })).data
          entry.task_id = task.id
          await putEntry(entry)
        }
        for (const p of entry.photos) {
          if (p.done) continue
          const fd = new FormData()
          fd.append('file', p.blob, p.name)
          fd.append('client_id', p.client_id)
          if (p.lastModified) fd.append('last_modified', String(p.lastModified))
          if (p.exif_datetime) fd.append('exif_datetime', p.exif_datetime)
          if (p.exif_offset) fd.append('exif_offset', p.exif_offset)
          await api.post(`/tasks/${entry.task_id}/attachments`, fd, { silent: true, timeout: 120000 })
          p.done = true
          await putEntry(entry)
        }
        await deleteEntry(entry.key)
        await this.refresh()
        this.online = true
        this.lastSyncedTaskIds = [...this.lastSyncedTaskIds, entry.task_id]
        return task || { id: entry.task_id }
      } catch (err) {
        if (isNetworkError(err)) {
          this.online = false
          entry.error = null
          await putEntry(entry)
          await this.refresh()
          return null
        }
        if (err.response?.status === 401) throw err // 登录过期：草稿保留，重新登录后再同步
        entry.error = err.response?.data?.detail || String(err.response?.status || err.message)
        await putEntry(entry)
        await this.refresh()
        throw err
      }
    },

    /** 同步全部；返回成功条数 */
    async syncAll() {
      if (this.syncing) return 0
      this.syncing = true
      let n = 0
      try {
        await this.refresh()
        for (const e of [...this.entries]) {
          try {
            if (await this.syncEntry(e)) n++
            else break // 网络不通，后面的也不用试了
          } catch {
            /* 已记录在 entry.error */
          }
        }
      } finally {
        this.syncing = false
      }
      return n
    },

    async discard(key) {
      await deleteEntry(key)
      await this.refresh()
    },
  },
})
