<script setup>
import { useI18n } from 'vue-i18n'
defineProps({ kind: { type: String, required: true } })
const { t } = useI18n()
</script>

<template>
  <span :class="['shift-tag', `shift-${kind}`]">{{ t(`shift.${kind}`) }}</span>
</template>
