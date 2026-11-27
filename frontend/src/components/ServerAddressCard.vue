<script setup>
// 系统设置 → 访问地址（管理员）：服务器 IP 变了在这里改，和在服务器上运行 set-address.ps1 一样
// （改 HTTPS 服务的地址并重启它；根证书不变，手机不用重装证书）。后端写请求文件、启动计划任务，结果写回来。
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { ElMessage, ElMessageBox } from 'element-plus'
import api from '../api'
import { translateError } from '../apiErrors'

const { t, locale } = useI18n()
const st = ref(null)
const input = ref('')
const busy = ref(false)
const submitted = ref('') // 刚提交的新地址：给出新地址的链接（旧地址可能马上打不开了）
let timer = null

async function load() {
  try {
    st.value = (await api.get('/server-address', { silent: true })).data
    if (!input.value) input.value = st.value.hosts
    if (submitted.value && !st.value.pending) stopPoll() // 计划任务处理完了
  } catch {
    // 地址刚改好、旧地址打不开了：保留页面上的新地址链接
  }
}
onMounted(load)
onUnmounted(() => stopPoll())
function stopPoll() { if (timer) { clearInterval(timer); timer = null } }

const first = (s) => (s || '').split(',')[0].trim()
const newUrl = computed(() => `https://${first(submitted.value)}`)
// 填的 IP 不是这台服务器自己的：多半填错了，保存后可能谁都打不开
const isIp = (h) => /^\d+\.\d+\.\d+\.\d+$/.test(h)
const changed = computed(() => input.value.trim() && input.value.replace(/\s/g, '') !== (st.value?.hosts || '').replace(/\s/g, ''))
// 只在改了地址、而且查得到这台服务器的 IP 时才提醒（查不到就不乱报）
const unknownIp = computed(() => {
  const ips = (st.value?.candidates || []).filter(isIp)
  if (!changed.value || !ips.length) return []
  return input.value.split(/[,，\s]+/).filter(isIp).filter((h) => !ips.includes(h))
})

function pick(h) { input.value = h }

async function save() {
  const warn = unknownIp.value.length ? `<p style="color:var(--el-color-danger)">${t('addr.unknownIp', { ip: unknownIp.value.join(', ') })}</p>` : ''
  await ElMessageBox.confirm(`${warn}<p>${t('addr.confirm', { url: `https://${first(input.value)}` })}</p>`, t('addr.title'),
    { type: 'warning', dangerouslyUseHTMLString: true, confirmButtonText: t('addr.apply'), cancelButtonText: t('common.cancel') })
  busy.value = true
  try {
    st.value = (await api.put('/server-address', { hosts: input.value }, { silent: true })).data
    submitted.value = st.value.pending || input.value
    stopPoll()
    timer = setInterval(load, 3000)
    setTimeout(stopPoll, 90000)
  } catch (e) {
    ElMessage.error(translateError(e.response?.data?.detail || '', locale.value, t) || t('common.requestFailed'))
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <el-card v-if="st" shadow="never" class="mb addr-card">
    <template #header>{{ t('addr.title') }}</template>
    <div class="now">
      <span class="muted">{{ t('addr.now') }}</span>
      <b v-if="st.hosts">https://{{ first(st.hosts) }}</b><span v-else class="muted">—</span>
      <span v-if="st.hosts.includes(',')" class="muted small">（{{ st.hosts }}）</span>
    </div>
    <el-form label-position="top" @submit.prevent>
      <el-form-item :label="t('addr.new')">
        <div class="row">
          <el-input v-model="input" placeholder="192.168.1.60" :disabled="!st.windows" />
          <el-button type="primary" :loading="busy" :disabled="!st.windows || !changed" @click="save">{{ t('addr.apply') }}</el-button>
        </div>
        <div class="cands">
          <template v-if="st.candidates.length">
            <span class="muted small">{{ t('addr.thisServer') }}</span>
            <el-tag v-for="c in st.candidates" :key="c" size="small" effect="plain" class="cand" @click="pick(c)">{{ c }}</el-tag>
          </template>
        </div>
        <small :class="['hint', unknownIp.length ? 'err' : 'muted']">
          {{ unknownIp.length ? t('addr.unknownIp', { ip: unknownIp.join(', ') }) : (st.windows ? t('addr.hint') : t('addr.notWindows')) }}
        </small>
      </el-form-item>
    </el-form>
    <!-- 结果区一直占位，提交后不跳 -->
    <div class="result">
      <template v-if="submitted">
        <el-alert :type="st.pending ? 'info' : (st.status?.ok ? 'success' : 'error')" :closable="false" show-icon>
          <template #title>
            <span v-if="st.pending">{{ t('addr.working') }}</span>
            <span v-else-if="st.status?.ok">{{ t('addr.done') }}</span>
            <span v-else>{{ t('addr.failed') }}：{{ st.status?.message }}</span>
            <a :href="newUrl" class="link">{{ newUrl }}</a>
          </template>
        </el-alert>
      </template>
      <span v-else-if="st.status" class="muted small">
        {{ t('addr.last', { at: st.status.at, hosts: st.status.hosts }) }}
        <b :class="st.status.ok ? 'ok' : 'err'">{{ st.status.ok ? t('addr.ok') : t('addr.failed') + '：' + st.status.message }}</b>
      </span>
    </div>
  </el-card>
</template>

<style scoped>
.mb { margin-bottom: 16px; }
.now { display: flex; gap: 8px; align-items: baseline; flex-wrap: wrap; margin-bottom: 10px; }
.row { display: flex; gap: 8px; width: 100%; }
.cands { display: flex; gap: 6px; align-items: center; flex-wrap: wrap; min-height: 26px; margin-top: 6px; width: 100%; }
.cand { cursor: pointer; }
.hint { display: block; width: 100%; line-height: 1.5; margin-top: 2px; min-height: 3em; }
.result { min-height: 48px; }
.link { margin-left: 8px; font-weight: 600; }
.muted { color: #909399; }
.small { font-size: 12px; }
.ok { color: #67c23a; }
.err { color: #f56c6c; }
</style>
