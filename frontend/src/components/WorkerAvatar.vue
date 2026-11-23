<script setup>
// 员工头像：有头像显示图片，没有则显示名字的第一个字
import { computed } from 'vue'

const props = defineProps({ worker: { type: Object, required: true }, size: { type: Number, default: 36 } })
const initial = computed(() => (props.worker.name || '?').trim().charAt(0).toUpperCase())
// 名字决定一个固定的底色，同一个人每次颜色一样
const COLORS = ['#409eff', '#67c23a', '#e6a23c', '#9b59b6', '#16a085', '#d35400', '#2c3e50', '#c0392b']
const color = computed(() => COLORS[[...(props.worker.name || '')].reduce((a, c) => a + c.charCodeAt(0), 0) % COLORS.length])
</script>

<template>
  <span class="av" :style="{ width: size + 'px', height: size + 'px', fontSize: size * 0.42 + 'px', background: worker.avatar_url ? '#eee' : color }">
    <img v-if="worker.avatar_url" :src="worker.avatar_url" :alt="worker.name" loading="lazy" />
    <span v-else>{{ initial }}</span>
  </span>
</template>

<style scoped>
.av { display: inline-flex; align-items: center; justify-content: center; border-radius: 50%; overflow: hidden; color: #fff; font-weight: 600; flex: none; }
.av img { width: 100%; height: 100%; object-fit: cover; }
</style>
