<script setup>
// 三语同时显示：上面是当前语言（没有译文时显示原文），下面小字列出另外两种语言
// 人工校对过的标「人工校对」，原文标「原文」；翻译还没出来时只显示原文
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'

const props = defineProps({
  tri: { type: Object, required: true },
  srcLang: { type: String, default: null },
  field: { type: String, required: true },
  manualFields: { type: Array, default: () => [] },
  compact: { type: Boolean, default: false }, // 列表卡片里用：译文各占一行、超长省略
})
const { t, locale } = useI18n()
const LABEL = { zh: '中', sr: 'SR', en: 'EN' }

const src = computed(() => props.srcLang || ['zh', 'sr', 'en'].find((l) => props.tri[l]))
const mainLang = computed(() => (props.tri[locale.value] ? locale.value : src.value))
const others = computed(() => ['zh', 'sr', 'en']
  .filter((l) => l !== mainLang.value && props.tri[l])
  .map((l) => ({ lang: l, text: props.tri[l], source: l === src.value, manual: props.manualFields.includes(`${props.field}_${l}`) })))
</script>

<template>
  <div :class="['tt', { compact }]">
    <div class="text">{{ tri[mainLang] }}</div>
    <div v-for="o in others" :key="o.lang" class="sub">
      <span class="lg">{{ LABEL[o.lang] }}</span>
      <span class="st">{{ o.text }}</span>
      <span v-if="o.source" class="tag">{{ t('tr.source') }}</span>
      <span v-else-if="o.manual" class="tag ok">{{ t('tr.manual') }}</span>
    </div>
  </div>
</template>

<style scoped>
.text { white-space: pre-wrap; word-break: break-word; }
.sub { display: flex; gap: 6px; align-items: baseline; font-size: 12.5px; color: #73767a; margin-top: 2px; line-height: 1.45; }
.lg { flex: none; font-size: 10px; font-weight: 600; color: #909399; border: 1px solid #dcdfe6; border-radius: 3px; padding: 0 3px; line-height: 15px; }
.st { white-space: pre-wrap; word-break: break-word; }
.compact .st { white-space: nowrap; overflow: hidden; text-overflow: ellipsis; min-width: 0; }
.tag { flex: none; font-size: 10px; color: #909399; }
.tag.ok { color: #67c23a; }
</style>
