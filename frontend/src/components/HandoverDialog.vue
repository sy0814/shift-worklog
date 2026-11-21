<script setup>
// 移交对话框：默认选系统建议的接班班组，可改；可填交接说明
import { ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { ElMessage } from 'element-plus'
import api from '../api'
import { localName } from '../i18n'
import { useAuth } from '../stores/auth'

const props = defineProps({ taskIds: { type: Array, required: true }, teamId: { type: Number, default: null } })
const visible = defineModel({ type: Boolean })
const emit = defineEmits(['done'])
const { t, locale } = useI18n()
const auth = useAuth()

const toTeam = ref(null)
const suggested = ref(null)
const note = ref('')
const busy = ref(false)

watch(visible, async (v) => {
  if (!v) return
  note.value = ''
  toTeam.value = suggested.value = null
  if (props.teamId) {
    const { data } = await api.get('/handover/default', { params: { team_id: props.teamId } })
    suggested.value = toTeam.value = data.to_team_id
  }
})

async function submit() {
  busy.value = true
  try {
    const { data } = await api.post('/handover', {
      task_ids: props.taskIds, to_team_id: toTeam.value, note: note.value.trim() || null, lang: locale.value,
    })
    ElMessage.success(t('ho.done', { n: data.length }))
    visible.value = false
    emit('done', data)
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <el-dialog v-model="visible" :title="`${t('ho.handover')} (${taskIds.length})`" width="min(480px, 94vw)" append-to-body>
    <el-form label-position="top">
      <el-form-item :label="t('ho.to')">
        <el-radio-group v-model="toTeam" class="teams">
          <el-radio-button v-for="tm in auth.teams.filter((x) => x.id !== teamId)" :key="tm.id" :value="tm.id">
            {{ localName(tm) }}<small v-if="tm.id === suggested"> · {{ t('ho.suggested') }}</small>
          </el-radio-button>
        </el-radio-group>
      </el-form-item>
      <el-form-item :label="t('ho.note')">
        <el-input v-model="note" type="textarea" :autosize="{ minRows: 3, maxRows: 8 }" :placeholder="t('ho.notePh')" maxlength="5000" />
      </el-form-item>
    </el-form>
    <template #footer>
      <el-button @click="visible = false">{{ t('common.cancel') }}</el-button>
      <el-button type="primary" :loading="busy" :disabled="!toTeam" @click="submit">{{ t('ho.handover') }}</el-button>
    </template>
  </el-dialog>
</template>

<style scoped>
.teams { flex-wrap: wrap; }
small { opacity: .75; }
</style>
