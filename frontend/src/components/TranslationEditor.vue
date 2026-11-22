<script setup>
// 人工校对译文：每段文字显示原文（只读）和另外两种语言（可改）
import { computed, reactive, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { ElMessage } from 'element-plus'
import api from '../api'

const props = defineProps({ task: { type: Object, required: true } })
const visible = defineModel({ type: Boolean })
const emit = defineEmits(['saved'])
const { t } = useI18n()
const LANG_LABEL = { zh: '中文', sr: 'Srpski', en: 'English' }
const FIELDS = [
  { key: 'content', tri: 'content', src: 'source_lang' },
  { key: 'leftover', tri: 'leftover', src: 'leftover_source_lang' },
  { key: 'discard_reason', tri: 'discard_reason', src: 'discard_reason_lang' },
]
const form = reactive({})
const saving = ref(false)

const fields = computed(() => FIELDS
  .map((f) => ({ ...f, srcLang: props.task[f.src], values: props.task[f.tri] }))
  .filter((f) => f.srcLang && f.values?.[f.srcLang]))

watch(visible, (v) => {
  if (!v) return
  for (const f of fields.value) for (const l of ['zh', 'sr', 'en']) form[`${f.key}_${l}`] = f.values[l] || ''
})

async function save() {
  saving.value = true
  try {
    for (const f of fields.value) {
      for (const l of ['zh', 'sr', 'en']) {
        if (l === f.srcLang) continue
        const v = (form[`${f.key}_${l}`] || '').trim()
        if (v && v !== (f.values[l] || '')) {
          await api.put(`/tasks/${props.task.id}/translation`, { field: f.key, lang: l, text: v })
        }
      }
    }
    ElMessage.success(t('common.saved'))
    visible.value = false
    emit('saved')
  } finally {
    saving.value = false
  }
}
</script>

<template>
  <el-dialog v-model="visible" :title="t('tr.correct')" width="min(640px, 96vw)" append-to-body>
    <div v-for="f in fields" :key="f.key" class="field">
      <h4>{{ t(`tr.fields.${f.key}`) }}</h4>
      <div class="src"><b>{{ t('tr.source') }} · {{ LANG_LABEL[f.srcLang] }}</b><div class="pre">{{ f.values[f.srcLang] }}</div></div>
      <template v-for="l in ['zh', 'sr', 'en']" :key="l">
        <div v-if="l !== f.srcLang" class="row">
          <label>{{ LANG_LABEL[l] }}
            <el-tag v-if="task.manual_fields.includes(`${f.key}_${l}`)" size="small" type="success">{{ t('tr.manual') }}</el-tag>
          </label>
          <el-input v-model="form[`${f.key}_${l}`]" type="textarea" :autosize="{ minRows: 2, maxRows: 8 }" />
        </div>
      </template>
    </div>
    <template #footer>
      <el-button @click="visible = false">{{ t('common.cancel') }}</el-button>
      <el-button type="primary" :loading="saving" @click="save">{{ t('common.save') }}</el-button>
    </template>
  </el-dialog>
</template>

<style scoped>
.field + .field { margin-top: 16px; border-top: 1px solid #eee; padding-top: 8px; }
h4 { margin: 4px 0 8px; }
.src { background: #f4f4f5; padding: 8px; border-radius: 4px; margin-bottom: 8px; font-size: 13px; }
.pre { white-space: pre-wrap; margin-top: 4px; }
.row { margin-bottom: 8px; }
.row label { display: flex; gap: 6px; align-items: center; font-size: 13px; color: #606266; margin-bottom: 4px; }
</style>
