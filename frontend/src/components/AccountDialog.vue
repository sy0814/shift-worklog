<script setup>
// 名册里某个人的登录账号：开账号、改用户名、重设密码、解锁、停用。
// 登录方式由角色决定：个人账号（用户名 + 密码 ≥6 位）/ 班组账号（点头像 + 个人密码 ≥4 位，可以和别人一样）
import { computed, reactive, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { ElMessage } from 'element-plus'
import dayjs from 'dayjs'
import api from '../api'
import { useAuth } from '../stores/auth'

const props = defineProps({ worker: { type: Object, default: null } })
const visible = defineModel({ type: Boolean })
const emit = defineEmits(['saved'])
const { t } = useI18n()
const auth = useAuth()
const acc = ref(null)
const form = reactive({ username: '', password: '' })

async function load() {
  acc.value = (await api.get(`/workers/${props.worker.id}/account`)).data
  form.username = acc.value.username || ''
  form.password = ''
}
watch(visible, (v) => v && props.worker && load())

const pin = computed(() => acc.value?.login_mode === 'pin')
const minLen = computed(() => (pin.value ? 4 : 6))
const canSave = computed(() => {
  if (!acc.value) return false
  const needName = !pin.value && !acc.value.user_id
  if (needName && !form.username.trim()) return false
  if (!acc.value.user_id && !form.password) return false
  return !form.password || form.password.length >= minLen.value || form.username !== (acc.value.username || '')
})
async function save(extra = {}) {
  const body = { ...extra }
  if (form.password) body.password = form.password
  if (!pin.value && form.username.trim() && form.username !== acc.value.username) body.username = form.username.trim()
  acc.value = (await api.put(`/workers/${props.worker.id}/account`, body)).data
  form.password = ''
  ElMessage.success(t('common.saved'))
  emit('saved')
}
async function unlock() {
  await api.post(`/users/${acc.value.user_id}/unlock`)
  load()
}
</script>

<template>
  <el-dialog v-model="visible" :title="worker ? t('acc.title', { n: worker.name }) : ''" width="min(440px, 94vw)" append-to-body>
    <template v-if="acc">
      <el-alert :type="pin ? 'info' : 'success'" :closable="false" show-icon class="mb"
                :title="pin ? t('acc.pinMode') : t('acc.pwMode')" :description="pin ? t('acc.pinHint') : t('acc.pwHint')" />
      <div v-if="acc.user_id" class="status">
        <el-tag v-if="acc.locked" type="danger">{{ t('acc.locked') }}</el-tag>
        <el-tag v-else-if="!acc.is_active" type="info">{{ t('acc.disabled') }}</el-tag>
        <el-tag v-else type="success">{{ t('acc.active') }}</el-tag>
        <span class="muted small">{{ t('users.lastLogin') }}: {{ acc.last_login_at ? dayjs(acc.last_login_at).format('MM-DD HH:mm') : '—' }}</span>
        <el-button v-if="acc.locked && auth.isAdmin" link type="warning" @click="unlock">{{ t('acc.unlock') }}</el-button>
      </div>
      <div v-else class="muted mb">{{ t('acc.none') }}</div>
      <el-form label-position="top" @submit.prevent>
        <el-form-item v-if="!pin" :label="t('users.username')">
          <el-input v-model="form.username" :disabled="!auth.isAdmin" autocomplete="off" />
        </el-form-item>
        <el-form-item :label="acc.user_id ? t('acc.newSecret') : (pin ? t('acc.pin') : t('users.password'))">
          <el-input v-model="form.password" type="password" show-password autocomplete="new-password" :inputmode="pin ? 'numeric' : 'text'"
                    :placeholder="`≥ ${minLen}`" />
        </el-form-item>
      </el-form>
    </template>
    <template #footer>
      <el-button v-if="acc?.user_id" :type="acc.is_active ? 'danger' : 'success'" plain @click="save({ is_active: !acc.is_active })">
        {{ acc.is_active ? t('acc.disable') : t('acc.enable') }}
      </el-button>
      <el-button @click="visible = false">{{ t('common.close') }}</el-button>
      <el-button type="primary" :disabled="!canSave" @click="save()">{{ acc?.user_id ? t('common.save') : t('acc.open') }}</el-button>
    </template>
  </el-dialog>
</template>

<style scoped>
.mb { margin-bottom: 12px; }
.status { display: flex; gap: 8px; align-items: center; margin-bottom: 12px; flex-wrap: wrap; }
.muted { color: #909399; }
.small { font-size: 12px; }
</style>
