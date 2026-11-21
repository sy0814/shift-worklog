<script setup>
// 已上传图片：缩略图 + 拍摄时间，点击大图浏览
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { Delete } from '@element-plus/icons-vue'
import { fmtFull, fmtTime } from '../format'

const props = defineProps({ photos: { type: Array, required: true }, canDelete: Boolean })
const emit = defineEmits(['delete'])
const { t } = useI18n()
const previews = computed(() => props.photos.map((p) => p.url_view))
</script>

<template>
  <div v-if="photos.length" class="grid">
    <div v-for="(p, i) in photos" :key="p.id" class="cell">
      <el-image :src="p.url_thumb" :preview-src-list="previews" :initial-index="i" fit="cover" lazy preview-teleported hide-on-click-modal />
      <div class="time" :title="`${t('photo.takenAt')} ${fmtFull(p.taken_at)} · ${t('photo.src_' + p.taken_at_source)}`">
        <span :class="['dot', p.taken_at_source]" />{{ fmtTime(p.taken_at) }}
      </div>
      <button v-if="canDelete" type="button" class="rm" :title="t('photo.remove')" @click="emit('delete', p)">
        <el-icon><Delete /></el-icon>
      </button>
    </div>
  </div>
</template>

<style scoped>
.grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(96px, 1fr)); gap: 6px; }
.cell { position: relative; aspect-ratio: 1; border-radius: 6px; overflow: hidden; background: #eee; }
.cell :deep(.el-image) { width: 100%; height: 100%; }
.time { position: absolute; left: 0; right: 0; bottom: 0; font-size: 11px; background: rgba(0,0,0,.55); color: #fff; padding: 2px 4px; display: flex; align-items: center; gap: 4px; }
.dot { width: 6px; height: 6px; border-radius: 50%; background: #67c23a; flex: none; }
.dot.file { background: #e6a23c; }
.dot.upload { background: #f56c6c; }
.rm { position: absolute; top: 2px; right: 2px; border: 0; border-radius: 50%; width: 24px; height: 24px; background: rgba(0,0,0,.6); color: #fff; display: flex; align-items: center; justify-content: center; padding: 0; cursor: pointer; }
</style>
