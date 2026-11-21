<script setup>
// 还没上传的本地图片预览
import { onUnmounted, watch, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { Close } from '@element-plus/icons-vue'

const props = defineProps({ photos: { type: Array, required: true } })
const emit = defineEmits(['remove'])
const { t } = useI18n()
const urls = ref([])

watch(() => props.photos.length, () => {
  urls.value.forEach(URL.revokeObjectURL)
  urls.value = props.photos.map((p) => URL.createObjectURL(p.blob))
}, { immediate: true })
onUnmounted(() => urls.value.forEach(URL.revokeObjectURL))
</script>

<template>
  <div v-if="photos.length" class="grid">
    <div v-for="(p, i) in photos" :key="p.client_id" class="cell">
      <img :src="urls[i]" :alt="p.name" />
      <span class="badge">{{ t('photo.waiting') }}</span>
      <button type="button" class="rm" @click="emit('remove', i)"><el-icon><Close /></el-icon></button>
    </div>
  </div>
</template>

<style scoped>
.grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(84px, 1fr)); gap: 6px; margin-top: 8px; width: 100%; }
.cell { position: relative; aspect-ratio: 1; border-radius: 6px; overflow: hidden; background: #eee; }
.cell img { width: 100%; height: 100%; object-fit: cover; }
.badge { position: absolute; left: 0; right: 0; bottom: 0; font-size: 11px; background: rgba(0,0,0,.55); color: #fff; padding: 2px 4px; }
.rm { position: absolute; top: 2px; right: 2px; border: 0; border-radius: 50%; width: 22px; height: 22px; background: rgba(0,0,0,.6); color: #fff; display: flex; align-items: center; justify-content: center; padding: 0; cursor: pointer; }
</style>
