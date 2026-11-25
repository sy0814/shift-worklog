<script setup>
// 弹窗形式的「为什么？」（排班日历、首页人员状态里用）
import { useI18n } from 'vue-i18n'
import { isNarrow } from '../format'
import WhyPanel from './WhyPanel.vue'

defineProps({ type: { type: String, required: true }, id: { type: Number, default: 0 }, day: { type: String, default: '' }, title: { type: String, default: '' } })
const visible = defineModel({ type: Boolean })
const { t } = useI18n()
</script>

<template>
  <el-dialog v-model="visible" :title="title || t('why.title')" width="min(560px, 96vw)" :fullscreen="isNarrow()" append-to-body destroy-on-close>
    <WhyPanel v-if="visible && id" :type="type" :id="id" :day="day" />
  </el-dialog>
</template>
