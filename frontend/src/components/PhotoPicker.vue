<script setup>
// 手机：「拍照」调用相机，「从相册选择」打开系统媒体库；电脑：选择图片文件
import { ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { Camera, Picture } from '@element-plus/icons-vue'
import { isTouch } from '../format'

const emit = defineEmits(['pick'])
const { t } = useI18n()
const touch = isTouch()
const cam = ref()
const lib = ref()

function onChange(e) {
  const files = [...e.target.files].filter((f) => f.type.startsWith('image/') || /\.(heic|heif)$/i.test(f.name))
  if (files.length) emit('pick', files)
  e.target.value = ''
}
</script>

<template>
  <div class="picker">
    <el-button v-if="touch" :icon="Camera" @click="cam.click()">{{ t('photo.camera') }}</el-button>
    <el-button :icon="Picture" @click="lib.click()">{{ touch ? t('photo.gallery') : t('photo.file') }}</el-button>
    <input ref="cam" type="file" accept="image/*" capture="environment" hidden @change="onChange" />
    <input ref="lib" type="file" accept="image/*,.heic,.heif" multiple hidden @change="onChange" />
  </div>
</template>

<style scoped>
.picker { display: flex; gap: 8px; flex-wrap: wrap; }
.picker .el-button + .el-button { margin-left: 0; }
</style>
