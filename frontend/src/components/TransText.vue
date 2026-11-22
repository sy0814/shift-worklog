<script setup>
// 显示一段三语文字：当前语言有译文就显示译文（标注机器翻译 / 人工校对，可展开看原文），否则显示原文
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'

const props = defineProps({
  tri: { type: Object, required: true },
  srcLang: { type: String, default: null },
  field: { type: String, required: true },
  manualFields: { type: Array, default: () => [] },
})
const { t, locale } = useI18n()
const showOrig = ref(false)

const src = computed(() => (props.srcLang && props.tri[props.srcLang]) || props.tri.zh || props.tri.sr || props.tri.en || '')
const translated = computed(() => props.srcLang && locale.value !== props.srcLang && !!props.tri[locale.value])
const text = computed(() => (translated.value ? props.tri[locale.value] : src.value))
const manual = computed(() => props.manualFields.includes(`${props.field}_${locale.value}`))
</script>

<template>
  <div class="tt">
    <div class="text">{{ text }}</div>
    <div v-if="srcLang && locale !== srcLang" class="meta">
      <template v-if="translated">
        <span :class="manual ? 'manual' : 'machine'">{{ manual ? t('tr.manual') : t('tr.machine') }}</span>
        · <a href="#" @click.prevent="showOrig = !showOrig">{{ showOrig ? t('tr.hideOriginal') : t('tr.showOriginal') }} ({{ srcLang }})</a>
      </template>
      <span v-else class="machine">{{ t('tr.source') }} ({{ srcLang }})</span>
    </div>
    <div v-if="showOrig && translated" class="orig">{{ src }}</div>
  </div>
</template>

<style scoped>
.text { white-space: pre-wrap; word-break: break-word; }
.meta { font-size: 12px; color: #909399; margin-top: 2px; }
.meta a { color: #409eff; text-decoration: none; }
.manual { color: #67c23a; }
.orig { margin-top: 4px; padding: 6px 8px; background: #f4f4f5; border-radius: 4px; color: #606266; white-space: pre-wrap; font-size: 13px; }
</style>
