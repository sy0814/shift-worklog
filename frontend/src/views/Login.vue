<script setup>
// 登录：个人账号（用户名 + 密码）/ 班组账号（选班组 → 点自己的头像 → 输入自己的密码）
import { appTitle } from '../branding'
import { computed, nextTick, onMounted, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { ElMessage } from 'element-plus'
import { Lock } from '@element-plus/icons-vue'
import api from '../api'
import { localName } from '../i18n'
import { useAuth } from '../stores/auth'
import LangSwitch from '../components/LangSwitch.vue'
import WorkerAvatar from '../components/WorkerAvatar.vue'

const { t, locale } = useI18n()
const auth = useAuth()
const router = useRouter()
const route = useRoute()

const read = (k) => { try { return localStorage.getItem(k) } catch { return null } }
const save = (k, v) => { try { localStorage.setItem(k, v) } catch { /* 存不了就算了 */ } }

const mode = ref(read('login_mode') || 'personal') // personal / team
watch(mode, (v) => save('login_mode', v))
const loading = ref(false)

function fail(e) {
  ElMessage.closeAll()
  const st = e?.response?.status
  const m = /(\d+) min/.exec(e?.response?.data?.detail || '')
  ElMessage.error(st === 423 ? t('login.locked', { n: m ? m[1] : 10 }) : t('login.failed'))
}
const done = () => router.replace(route.query.next || '/')

// ---- 个人账号 ----
const form = reactive({ username: '', password: '' })
async function submit() {
  if (!form.username || !form.password) return
  loading.value = true
  try {
    await auth.login(form.username.trim(), form.password)
    done()
  } catch (e) {
    if (e?.response?.data?.detail === 'use team login') { ElMessage.closeAll(); ElMessage.warning(t('login.useTeam')); mode.value = 'team'; return }
    fail(e)
  } finally {
    loading.value = false
  }
}

// ---- 班组账号 ----
const teams = ref([])
const teamId = ref(Number(read('login_team')) || null) // 记住上次选的班组（共用手机时方便）
const people = ref([])
const person = ref(null)
const pin = ref('')
const pinInput = ref()
async function loadTeams() {
  teams.value = (await api.get('/auth/teams', { silent: true })).data
  if (teamId.value && !teams.value.some((x) => x.id === teamId.value)) teamId.value = null
  if (teamId.value) loadPeople()
}
async function loadPeople() {
  person.value = null
  people.value = teamId.value ? (await api.get(`/auth/teams/${teamId.value}/people`, { silent: true })).data : []
}
watch(teamId, (v) => { if (v) save('login_team', String(v)); loadPeople() })
watch(mode, (v) => { if (v === 'team' && !teams.value.length) loadTeams() })
onMounted(() => { if (mode.value === 'team') loadTeams() })
async function pick(p) {
  if (p.locked) return ElMessage.warning(t('login.locked', { n: 10 }))
  person.value = p
  pin.value = ''
  await nextTick()
  pinInput.value?.focus()
}
async function submitPin() {
  if (!person.value || !pin.value) return
  loading.value = true
  try {
    await auth.pinLogin(person.value.user_id, pin.value)
    done()
  } catch (e) {
    pin.value = ''
    fail(e)
    if (e?.response?.status === 423) loadPeople()
  } finally {
    loading.value = false
  }
}
const teamName = (tm) => localName(tm)
const teamLabel = computed(() => teams.value.find((x) => x.id === teamId.value))
</script>

<template>
  <div class="login-wrap">
    <el-card class="login-card">
      <div class="login-head">
        <h2>{{ appTitle(locale) }}</h2>
        <LangSwitch />
      </div>
      <el-segmented v-model="mode" :options="[{ value: 'personal', label: t('login.personal') }, { value: 'team', label: t('login.team') }]"
                    block size="large" class="modes" />

      <el-form v-if="mode === 'personal'" label-position="top" @submit.prevent="submit">
        <el-form-item :label="t('login.username')">
          <el-input v-model="form.username" autocomplete="username" size="large" />
        </el-form-item>
        <el-form-item :label="t('login.password')">
          <el-input v-model="form.password" type="password" show-password autocomplete="current-password" size="large" />
        </el-form-item>
        <el-button type="primary" native-type="submit" size="large" :loading="loading" style="width: 100%">
          {{ t('login.submit') }}
        </el-button>
      </el-form>

      <div v-else class="team-login">
        <div v-if="!teams.length" class="muted">{{ t('login.noTeams') }}</div>
        <div class="teams">
          <button v-for="tm in teams" :key="tm.id" type="button" :class="['tbtn', { on: tm.id === teamId }]" @click="teamId = tm.id">
            {{ teamName(tm) }}
          </button>
        </div>
        <template v-if="teamId">
          <div class="muted small">{{ t('login.pickYou', { team: teamLabel ? teamName(teamLabel) : '' }) }}</div>
          <div class="people">
            <button v-for="p in people" :key="p.user_id" type="button" :class="['pbtn', { on: person?.user_id === p.user_id, locked: p.locked }]" @click="pick(p)">
              <WorkerAvatar :worker="{ name: p.name, avatar_url: p.avatar_url }" :size="48" />
              <span class="pname">{{ p.name }}</span>
              <el-icon v-if="p.locked" class="lock"><Lock /></el-icon>
            </button>
          </div>
        </template>
        <el-form v-if="person" class="pinform" @submit.prevent="submitPin">
          <div class="who"><b>{{ person.name }}</b> · {{ t('login.yourPassword') }}</div>
          <el-input ref="pinInput" v-model="pin" type="password" inputmode="numeric" autocomplete="off" size="large" show-password />
          <el-button type="primary" native-type="submit" size="large" :loading="loading" :disabled="!pin" style="width: 100%">{{ t('login.submit') }}</el-button>
        </el-form>
      </div>
    </el-card>
  </div>
</template>

<style scoped>
.login-wrap { min-height: 100%; display: flex; align-items: center; justify-content: center; padding: 16px; box-sizing: border-box; }
.login-card { width: 100%; max-width: 420px; }
.login-head { display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px; }
.login-head h2 { margin: 0; font-size: 20px; }
.modes { margin-bottom: 14px; }
.muted { color: #909399; }
.small { font-size: 12px; margin: 10px 0 6px; }
.teams { display: flex; flex-wrap: wrap; gap: 8px; }
.tbtn { border: 1px solid #dcdfe6; background: #fff; border-radius: 18px; padding: 7px 14px; font-size: 15px; cursor: pointer; font-family: inherit; }
.tbtn.on { background: #409eff; border-color: #409eff; color: #fff; }
.people { display: grid; grid-template-columns: repeat(auto-fill, minmax(84px, 1fr)); gap: 8px; max-height: 46vh; overflow: auto; }
.pbtn { position: relative; display: flex; flex-direction: column; align-items: center; gap: 4px; padding: 8px 4px; border: 2px solid transparent;
  border-radius: 10px; background: #f5f7fa; cursor: pointer; font-family: inherit; }
.pbtn.on { border-color: #409eff; background: #ecf5ff; }
.pbtn.locked { opacity: .5; }
.pname { font-size: 13px; max-width: 100%; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.lock { position: absolute; top: 6px; right: 6px; color: #f56c6c; }
.pinform { display: flex; flex-direction: column; gap: 10px; margin-top: 14px; }
.who { font-size: 14px; }
</style>
