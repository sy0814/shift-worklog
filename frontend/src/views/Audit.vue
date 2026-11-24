<script setup>
// 操作记录（管理员）：像任务的修改记录一样逐条成句显示；左边下拉选账号，看这个人改了什么
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import dayjs from 'dayjs'
import api from '../api'
import { localName } from '../i18n'
import { fmtFull } from '../format'
import { shortEntry } from '../cycle'
import { useAuth } from '../stores/auth'
import TaskDetail from '../components/TaskDetail.vue'

const { t, te, locale } = useI18n()
const auth = useAuth()
const PAGE = 100
const users = ref([])
const filters = reactive({ user: 'all', entity: '', dates: null })
const rows = ref([])
const total = ref(0)
const loading = ref(false)

async function loadUsers() {
  users.value = (await api.get('/audit/users')).data
}
async function load(append = false) {
  loading.value = true
  try {
    const params = { lang: locale.value, limit: PAGE, offset: append ? rows.value.length : 0 }
    if (filters.user === 'system') params.user_id = -1
    else if (filters.user !== 'all') params.user_id = filters.user
    if (filters.entity) params.entity = filters.entity
    if (filters.dates) [params.date_from, params.date_to] = filters.dates
    const { data } = await api.get('/audit', { params })
    rows.value = append ? [...rows.value, ...data.items] : data.items
    total.value = data.total
  } finally {
    loading.value = false
  }
}
watch(() => [filters.user, filters.entity, filters.dates, locale.value], () => load())
onMounted(() => { loadUsers(); load() })

const ENTITIES = ['task', 'user', 'worker', 'attendance', 'overtime', 'inspection', 'glossary', 'holiday', 'shift_config', 'team', 'setting', 'ai_report', 'export', 'system']

// ---- 把同一次操作（同一人、同一对象、同一动作、2 秒内）的多条字段改动合成一句 ----
const entries = computed(() => {
  const out = []
  for (const r of rows.value) {
    const last = out[out.length - 1]
    if (last && last.user_id === r.user_id && last.entity === r.entity && last.entity_id === r.entity_id
        && last.action === r.action && Math.abs(dayjs(last.at).diff(r.at, 'second')) <= 2) {
      last.changes.push(r)
    } else {
      out.push({ ...r, changes: [r] })
    }
  }
  return out
})

function parse(v) {
  if (v == null) return null
  try { return JSON.parse(v) } catch { return v }
}
function fieldLabel(f) {
  const m = /^(content|leftover|discard_reason)_(zh|sr|en)$/.exec(f)
  if (m) return `${t('tr.fields.' + m[1])} (${m[2]})`
  if (f?.startsWith('perm:')) return t('rp.perms.' + f.slice(5).replace('.', '_')) // 角色权限的某一项
  return te(`log.field.${f}`) ? t(`log.field.${f}`) : f
}
function fmtVal(f, v) {
  v = parse(v)
  if (v == null || v === '') return '∅'
  if (f?.startsWith('perm:') && te(`rp.scopes.${v}`)) return t(`rp.scopes.${v}`)
  if (f === 'pattern' && Array.isArray(v)) return v.map((k) => shortEntry(k, t)).join(' ')
  if (f === 'schedule' && typeof v === 'object') { // 员工排班变更：从哪天起 · 班组 · 跟班组 / 个人循环
    const team = v.team_id ? localName(auth.teamById(v.team_id)) : t('ws.noTeam')
    const how = v.pattern ? `${t('ws.personal')} ${v.pattern.map((k) => shortEntry(k, t)).join(' ')}` : t('ws.follow')
    return `${v.from <= '2000-01-01' ? t('ws.since') : v.from} · ${team} · ${how}`
  }
  if (Array.isArray(v)) return v.join('、') || '∅'
  if (typeof v === 'boolean') return v ? t('common.yes') : t('common.no')
  if (f === 'team_shift' && /^\d{4}-\d{2}-\d{2} \w+$/.test(String(v))) {
    const [d, k] = String(v).split(' ')
    return `${d} ${te('shift.' + k) ? t('shift.' + k) : k}`
  }
  if (f === 'team_id' || f === 'to_team') return localName(auth.teamById(Number(v))) || String(v)
  if (f === 'status' && te(`status.${v}`)) return t(`status.${v}`)
  if (f === 'status' && te(`att.st.${v}`)) return t(`att.st.${v}`)
  if (f === 'role') return t(`users.${v}`)
  if (f === 'avatar') return '🖼'
  if (/(_at|^at_time)$/.test(f) || /^\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}/.test(String(v))) {
    const d = dayjs(String(v).replace(' ', 'T'))
    if (d.isValid() && String(v).length > 10) return fmtFull(String(v).replace(' ', 'T'))
  }
  if (typeof v === 'object') return Object.entries(v).map(([k, x]) => `${fieldLabel(k)}: ${x}`).join('；')
  const s = String(v)
  return s.length > 80 ? s.slice(0, 80) + '…' : s
}
const Q = computed(() => (locale.value === 'zh' ? ['「', '」'] : locale.value === 'sr' ? ['„', '”'] : ['“', '”']))
function who(e) {
  return e.user_id == null ? t('log.system') : (e.user_name || '#' + e.user_id)
}
function verb(e) {
  return te(`log.verb.${e.action}`) ? t(`log.verb.${e.action}`) : e.action
}
function target(e) {
  if (['login', 'change_password', 'seed', 'retry_failed', 'swap'].includes(e.action)) return ''
  if (e.action === 'locked') return `${t('log.ent.user')} ${e.label || ''}`
  const noun = te(`log.ent.${e.entity}`) ? t(`log.ent.${e.entity}`) : e.entity
  const name = e.label ? `${Q.value[0]}${e.label}${Q.value[1]}` : ''
  const id = /^\d+$/.test(e.entity_id) && e.entity !== 'holiday' ? ` #${e.entity_id}` : (e.label ? '' : ` ${e.entity_id}`)
  return `${noun}${id} ${name}`.trim()
}
// 每条记录下面显示的细节：字段改动 / 移交去向 / 图片名 / 废弃原因……
function details(e) {
  const out = []
  for (const c of e.changes) {
    if (['source_lang', 'leftover_source_lang', 'discard_reason_lang'].includes(c.field)) continue
    if (c.action === 'status' && c.field !== 'status') continue
    if (c.action === 'discard' && !/^discard_reason_/.test(c.field || '')) continue
    if (c.action === 'handover' && c.field === 'status') continue
    if (c.action === 'translate') continue
    if (c.action === 'create' || c.action === 'auto_create' || c.action === 'receive') continue
    if ((c.action === 'attach' || c.action === 'detach') && (c.new_value || c.old_value)) {
      out.push(c.new_value || c.old_value)
      continue
    }
    if (!c.field) continue
    if (c.action === 'discard') { out.push(`${t('ho.discardReason')}: ${fmtVal('', c.new_value)}`); continue }
    if (c.field === 'to_team') { out.push(`→ ${fmtVal('to_team', c.new_value)}`); continue }
    out.push(`${fieldLabel(c.field)}: ${fmtVal(c.field, c.old_value)} → ${fmtVal(c.field, c.new_value)}`)
  }
  return out
}

const detailOpen = ref(false)
const detailId = ref(null)
function openEntity(e) {
  if (e.entity === 'task' && /^\d+$/.test(e.entity_id)) {
    detailId.value = Number(e.entity_id)
    detailOpen.value = true
  }
}
const userLabel = (u) => (u.user_id == null ? t('log.system') : u.name === u.username ? u.username : `${u.name}（${u.username}）`)
</script>

<template>
  <div class="page">
    <h1 class="page-title">{{ t('nav.audit') }}</h1>
    <div class="layout">
      <aside class="filters">
        <el-select v-model="filters.user" filterable class="w">
          <el-option value="all" :label="t('log.allUsers')" />
          <el-option v-for="u in users" :key="u.user_id ?? 'system'" :value="u.user_id ?? 'system'" :label="userLabel(u)">
            <span>{{ userLabel(u) }}</span><span class="cnt">{{ u.count }}</span>
          </el-option>
        </el-select>
        <el-select v-model="filters.entity" clearable :placeholder="t('log.entity')" class="w">
          <el-option v-for="e in ENTITIES" :key="e" :value="e" :label="t(`log.ent.${e}`)" />
        </el-select>
        <el-date-picker v-model="filters.dates" type="daterange" value-format="YYYY-MM-DD" unlink-panels
                        :start-placeholder="t('log.dateRange')" :end-placeholder="t('log.dateRange')" class="w" />
        <div class="muted small">{{ total }}</div>
      </aside>

      <section v-loading="loading" class="list">
        <div v-if="!entries.length && !loading" class="muted">{{ t('log.empty') }}</div>
        <div v-for="e in entries" :key="e.id" :class="['entry', { link: e.entity === 'task' }]" @click="openEntity(e)">
          <div class="when">{{ fmtFull(e.at) }}</div>
          <div class="what">
            <b :class="{ sys: e.user_id == null }">{{ who(e) }}</b>
            {{ verb(e) }}
            <span class="target">{{ target(e) }}</span>
          </div>
          <ul v-if="details(e).length" class="details">
            <li v-for="(d, i) in details(e)" :key="i">{{ d }}</li>
          </ul>
        </div>
        <el-button v-if="rows.length < total" text class="more" @click="load(true)">{{ t('log.more') }} ({{ rows.length }}/{{ total }})</el-button>
      </section>
    </div>
    <TaskDetail v-model="detailOpen" :task-id="detailId" />
  </div>
</template>

<style scoped>
.layout { display: grid; grid-template-columns: 240px 1fr; gap: 16px; align-items: start; }
@media (max-width: 760px) { .layout { grid-template-columns: 1fr; } }
.filters { display: flex; flex-direction: column; gap: 8px; position: sticky; top: 64px; }
.w { width: 100% !important; box-sizing: border-box; }
.filters :deep(.el-date-editor.el-range-editor) { width: 100% !important; box-sizing: border-box; }
.cnt { float: right; color: #909399; font-size: 12px; margin-left: 12px; }
.list { background: #fff; border-radius: 8px; padding: 4px 16px; min-height: 120px; }
.entry { padding: 10px 0; border-bottom: 1px solid #f2f3f5; }
.entry.link { cursor: pointer; }
.entry.link:hover .target { color: #409eff; }
.when { font-size: 12px; color: #909399; }
.what { margin-top: 2px; line-height: 1.6; }
.sys { color: #909399; }
.target { color: #303133; font-weight: 500; }
.details { margin: 4px 0 0; padding-left: 18px; font-size: 13px; color: #606266; }
.details li { word-break: break-word; }
.muted { color: #909399; }
.small { font-size: 12px; }
.more { display: block; margin: 8px auto; }
</style>
