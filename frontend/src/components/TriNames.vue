<script setup>
// 三种语言的名称输入框 + 「自动翻译」按钮（把填了的那种翻成空着的语言，给人看过再保存）。
// 空着保存也行：服务器保存时会自动翻译空着的语言。
// prefix：字段名前缀（班组、角色用 'name_' → name_zh / name_sr / name_en；系统名称用 '' → zh / sr / en）
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { ElMessage } from 'element-plus'
import api from '../api'

const model = defineModel({ type: Object, required: true })
const props = defineProps({ prefix: { type: String, default: 'name_' }, maxlength: { type: Number, default: 50 },
  size: { type: String, default: 'default' }, placeholders: { type: Object, default: () => ({}) } })
const emit = defineEmits(['change'])
const { t } = useI18n()
const LANGS = [['zh', '中'], ['sr', 'SR'], ['en', 'EN']]
const key = (l) => props.prefix + l
const source = computed(() => LANGS.map(([l]) => l).find((l) => model.value[key(l)]?.trim()))
const empty = computed(() => LANGS.some(([l]) => !model.value[key(l)]?.trim()))
const busy = ref(false)
async function translate() {
  if (!source.value) return
  busy.value = true
  try {
    const r = (await api.post('/translate', { text: model.value[key(source.value)].trim() }, { timeout: 30000 })).data
    for (const [l] of LANGS) if (!model.value[key(l)]?.trim()) model.value[key(l)] = r[l]
    emit('change')
  } catch {
    ElMessage.closeAll()
    ElMessage.warning(t('names.failed'))
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <div class="tri">
    <el-input v-for="[l, label] in LANGS" :key="l" v-model="model[key(l)]" :size="size" :maxlength="maxlength"
              :placeholder="placeholders[l] || ''" clearable>
      <template #prepend>{{ label }}</template>
    </el-input>
    <div class="row">
      <el-button :size="size === 'small' ? 'small' : 'default'" :disabled="!source || !empty" :loading="busy" @click="translate">🌐 {{ t('names.translate') }}</el-button>
      <small class="muted">{{ t('names.hint') }}</small>
    </div>
  </div>
</template>

<style scoped>
.tri { display: flex; flex-direction: column; gap: 6px; width: 100%; }
.row { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }
.muted { color: #909399; font-size: 12px; line-height: 1.4; }
</style>
