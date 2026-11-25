<script setup>
// 顶栏的「待同步」提示：有离线草稿时显示数量，可手动同步或丢弃
import { onMounted, onUnmounted } from 'vue'
import { useI18n } from 'vue-i18n'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Upload } from '@element-plus/icons-vue'
import dayjs from 'dayjs'
import { useOutbox } from '../stores/outbox'
import { translateError } from '../apiErrors'

const { t, locale } = useI18n()
const outbox = useOutbox()

async function sync(manual = false) {
  if (!outbox.count) return
  const n = await outbox.syncAll()
  if (n) ElMessage.success(t('outbox.synced', { n }))
  else if (manual && !outbox.online) ElMessage.warning(t('outbox.offline'))
}
async function discard(e) {
  await ElMessageBox.confirm(t('outbox.confirmDiscard'), t('outbox.discard'), { type: 'warning' })
  await outbox.discard(e.key)
}

const onOnline = () => { outbox.online = true; sync() }
const onOffline = () => { outbox.online = false }
let timer
onMounted(async () => {
  await outbox.refresh()
  sync()
  window.addEventListener('online', onOnline)
  window.addEventListener('offline', onOffline)
  timer = setInterval(() => outbox.count && sync(), 60_000) // Wi-Fi 恢复时不一定触发 online 事件
})
onUnmounted(() => {
  window.removeEventListener('online', onOnline)
  window.removeEventListener('offline', onOffline)
  clearInterval(timer)
})
</script>

<template>
  <el-popover v-if="outbox.count || !outbox.online" trigger="click" :width="300" placement="bottom-end">
    <template #reference>
      <el-badge :value="outbox.count || ''" :hidden="!outbox.count" type="warning">
        <el-button size="small" :type="outbox.online ? 'warning' : 'danger'" :icon="Upload" :loading="outbox.syncing" circle />
      </el-badge>
    </template>
    <div class="box">
      <div class="title">{{ t('outbox.title') }} <el-tag v-if="!outbox.online" type="danger" size="small">{{ t('outbox.offline') }}</el-tag></div>
      <div v-if="!outbox.count" class="muted">{{ t('outbox.none') }}</div>
      <div v-for="e in outbox.entries" :key="e.key" class="item">
        <div>
          <b v-if="e.type === 'status'">{{ t('outbox.statusTo') }} #{{ e.task_id }} → {{ t(`status.${e.status}`) }}</b>
          <b v-else-if="e.type === 'log'">{{ t('tlog.outbox') }} #{{ e.task_id }}</b>
          <b v-else>{{ e.type === 'task' ? t('outbox.newTask') : t('outbox.addPhotos') + ' #' + e.task_id }}</b>
          <span class="muted"> · {{ dayjs(e.saved_at).format('MM-DD HH:mm') }}</span>
        </div>
        <div v-if="e.task" class="text">{{ e.task.content }}</div>
        <div v-if="e.label" class="text">{{ e.label }}</div>
        <div v-if="e.photos.length" class="muted">{{ t('outbox.photos', { n: e.photos.filter((p) => !p.done).length }) }}</div>
        <div v-if="e.error" class="err">{{ t('outbox.failed') }}: {{ translateError(e.error, locale, t) }}
          <el-button link type="danger" size="small" @click="discard(e)">{{ t('outbox.discard') }}</el-button>
        </div>
      </div>
      <el-button v-if="outbox.count" type="primary" size="small" :loading="outbox.syncing" style="width: 100%" @click="sync(true)">{{ t('outbox.syncNow') }}</el-button>
    </div>
  </el-popover>
</template>

<style scoped>
.title { font-weight: 600; margin-bottom: 8px; display: flex; gap: 6px; align-items: center; }
.item { border-bottom: 1px solid #eee; padding: 6px 0; font-size: 13px; }
.text { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.muted { color: #909399; font-size: 12px; }
.err { color: #f56c6c; font-size: 12px; }
.box > .el-button { margin-top: 8px; }
</style>
