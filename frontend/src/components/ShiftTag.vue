<script setup>
// 班次标签。short：只写一个字（白 / 中 / 夜 / 休，塞语 P / D / T / S），手机上的排班日历用，鼠标放上去看全称
import { useI18n } from 'vue-i18n'
defineProps({ kind: { type: String, required: true }, short: { type: Boolean, default: false } })
const { t } = useI18n()
</script>

<template>
  <span :class="['shift-tag', `shift-${kind}`, { short }]" :title="short ? t(`shift.${kind}`) : undefined">{{ short ? t(`att.code.${kind}`) : t(`shift.${kind}`) }}</span>
</template>
