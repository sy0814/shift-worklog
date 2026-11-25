<script setup>
// 员工名册（系统管理员；车间管理员管本车间）：像表格一样点格子直接改（改完马上保存、留痕）、加行、加自定义列、Excel 导入导出
import RowActions from '../components/RowActions.vue'
import { computed, nextTick, onMounted, onUnmounted, reactive, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Plus } from '@element-plus/icons-vue'
import api, { download } from '../api'
import { localName } from '../i18n'
import { useAuth } from '../stores/auth'
import WorkerAvatar from '../components/WorkerAvatar.vue'
import WorkerScheduleDialog from '../components/WorkerScheduleDialog.vue'
import AccountDialog from '../components/AccountDialog.vue'

const { t, locale } = useI18n()
const auth = useAuth()
const rows = ref([])
const fields = ref([])
const showInactive = ref(false)
const teamFilter = ref(null)

async function load() {
  const [w, f] = await Promise.all([
    api.get('/workers', { params: { include_inactive: showInactive.value } }),
    api.get('/workers/fields'),
  ])
  rows.value = w.data
  fields.value = f.data
}
onMounted(load)
// 别人改了也能看到：没在编辑时每 30 秒刷新一次
const timer = setInterval(() => { if (!editing.key && !draft.value) load() }, 30000)
onUnmounted(() => clearInterval(timer))

// 班长（有「重设成员个人密码」权限）也能进来：只读，只看本班组，只能给班组账号的成员重设个人密码
const readonly = computed(() => !auth.deptOk('worker.manage'))
const shown = computed(() => rows.value.filter((w) => (!teamFilter.value || w.team_id === teamFilter.value)
  && (!auth.multiDept || w.department_id === auth.dept) // 多个车间时只列当前车间的人
  && (!readonly.value || auth.inGroup(w.team_id))))
// 角色
const roles = ref([])
api.get('/roles').then((r) => { roles.value = r.data }).catch(() => {})
const memberRole = computed(() => roles.value.find((r) => r.code === 'member'))
const roleOf = (w) => roles.value.find((r) => r.id === (w.role_id ?? memberRole.value?.id))
const roleLabel = (w) => { const r = roleOf(w); return r ? r[`name_${locale.value}`] : '' }
const canAccount = (w) => !readonly.value || (roleOf(w)?.login_mode === 'pin' && auth.teamOk('worker.pin', w.team_id))
// 车间管理员不能给人设「全厂」范围的角色
const assignableRoles = computed(() => roles.value.filter((r) => auth.isAdmin || auth.scope('worker.manage') === 'all'
  || !Object.values(r.permissions || {}).includes('all')))
const accOpen = ref(false)
const accWorker = ref(null)
function openAccount(w) { accWorker.value = w; accOpen.value = true }
async function setRole(w, roleId) {
  Object.assign(w, (await api.patch(`/workers/${w.id}`, { role_id: roleId })).data)
  flash(w.id, 'role_id')
}
const teamName = (id) => (id ? localName(auth.teamById(id)) : t('workers.noTeam'))

// ---------------- 逐格编辑 ----------------
// 列：name / employee_no / team_id / is_active / x<列id>
const editing = reactive({ id: null, key: null, value: null })
const isEditing = (w, key) => editing.id === w.id && editing.key === key
const valueOf = (w, key) => (key.startsWith('x') ? w.extra?.[key.slice(1)] ?? '' : w[key])
async function startEdit(w, key) {
  if (readonly.value) return
  if (isEditing(w, key)) return
  await commit()
  Object.assign(editing, { id: w.id, key, value: valueOf(w, key) ?? '' })
  await nextTick()
  document.querySelector('.cell-editor input')?.focus()
}
function cancel() {
  Object.assign(editing, { id: null, key: null, value: null })
}
let committing = false
async function commit() {
  if (!editing.key || committing) return
  const w = rows.value.find((x) => x.id === editing.id)
  const { key } = editing
  let v = editing.value
  cancel()
  if (!w) return
  if (typeof v === 'string') v = v.trim()
  if ((valueOf(w, key) ?? '') === (v ?? '')) return
  if (key === 'name' && !v) return
  const body = key.startsWith('x') ? { extra: { [key.slice(1)]: v || '' } }
    : { [key]: key === 'employee_no' ? (v || null) : v }
  committing = true
  try {
    const r = (await api.patch(`/workers/${w.id}`, body)).data
    Object.assign(w, r)
    flash(w.id, key)
  } catch { /* 出错时 api 已提示，值保持原样 */ } finally {
    committing = false
  }
}
// 保存后格子闪一下绿色
const flashed = ref('')
function flash(id, key) {
  flashed.value = `${id}|${key}`
  setTimeout(() => { if (flashed.value === `${id}|${key}`) flashed.value = '' }, 1200)
}
function onKey(e) {
  if (e.key === 'Enter') { e.preventDefault(); commit() }
  if (e.key === 'Escape') cancel()
}

// ---------------- 加行 ----------------
const draft = ref(null) // 正在新增的一行
async function addRow() {
  await commit()
  draft.value = { name: '', employee_no: '', team_id: teamFilter.value }
  await nextTick()
  document.querySelector('.draft input')?.focus()
}
async function saveDraft() {
  const d = draft.value
  if (!d || !d.name.trim()) { draft.value = null; return }
  draft.value = null
  const w = (await api.post('/workers', { name: d.name.trim(), employee_no: d.employee_no.trim() || null, team_id: d.team_id })).data
  rows.value.push(w)
  flash(w.id, 'name')
  ElMessage.success({ message: t('dp.added', { n: w.name }), duration: 4000 }) // 已自动开账号，默认密码，第一次登录要改
}
// 给名册里还没有账号的在职员工都开账号（默认密码）
async function openAll() {
  await ElMessageBox.confirm(t('dp.openAllConfirm'), t('dp.openAll'), { type: 'info' })
  const r = (await api.post('/workers/accounts/open-all')).data
  ElMessageBox.alert(t('dp.openAllDone', { n: r.created, p: r.password }), t('dp.openAll'), { type: 'success' })
}

// ---------------- 列 ----------------
async function addCol() {
  const { value } = await ElMessageBox.prompt(t('workers.colName'), t('workers.addCol'), { inputValidator: (v) => !!v?.trim() })
  await api.post('/workers/fields', { label: value.trim() })
  load()
}
async function colCommand(f, cmd) {
  if (cmd === 'rename') {
    const { value } = await ElMessageBox.prompt(t('workers.colName'), t('workers.renameCol'), { inputValue: f.label, inputValidator: (v) => !!v?.trim() })
    await api.put(`/workers/fields/${f.id}`, { label: value.trim() })
  } else {
    await ElMessageBox.confirm(t('workers.delColConfirm', { c: f.label }), t('workers.delCol'), { type: 'warning' })
    await api.delete(`/workers/fields/${f.id}`)
  }
  load()
}

// ---------------- 班组与排班（变更记录、个人循环）----------------
const wsOpen = ref(false)
const wsWorker = ref(null)
function openSchedule(w) {
  wsWorker.value = w
  wsOpen.value = true
}

// ---------------- 头像 ----------------
const avatarInput = ref()
const avatarFor = ref(null)
function avatarCommand(w, cmd) {
  if (cmd === 'remove') return removeAvatar(w)
  avatarFor.value = w
  avatarInput.value.click()
}
async function uploadAvatar(e) {
  const f = e.target.files[0]
  e.target.value = ''
  if (!f || !avatarFor.value) return
  const fd = new FormData()
  fd.append('file', f)
  Object.assign(avatarFor.value, (await api.post(`/workers/${avatarFor.value.id}/avatar`, fd, { timeout: 60000 })).data)
  ElMessage.success(t('common.saved'))
}
async function removeAvatar(w) {
  Object.assign(w, (await api.delete(`/workers/${w.id}/avatar`)).data)
  ElMessage.success(t('avatar.removed'))
}

// ---------------- Excel ----------------
const fileInput = ref()
async function importFile(e) {
  const f = e.target.files[0]
  e.target.value = ''
  if (!f) return
  const send = async (dry) => {
    const fd = new FormData()
    fd.append('file', f)
    return (await api.post('/workers/import', fd, { params: { dry_run: dry }, timeout: 120000 })).data
  }
  const pre = await send(true)
  if (pre.errors.length) return showErrors(pre.errors)
  const cols = pre.columns_added.length ? t('workers.importCols', { cols: pre.columns_added.join('、') }) : ''
  await ElMessageBox.confirm(t('workers.importPreview', { c: pre.created, u: pre.updated, cols }), t('workers.import'), { type: 'info' })
  const r = await send(false)
  if (r.errors.length) return showErrors(r.errors)
  ElMessage.success({ message: t('workers.importDone', { c: r.created, u: r.updated, n: r.unchanged }), duration: 5000 })
  load()
}
function showErrors(errs) {
  ElMessageBox.alert(errs.slice(0, 30).map((x) => `${t('att.row', { n: x.split(':')[0] })}：${x.split(':').slice(1).join(':')}`).join('\n'),
    t('workers.importErr', { n: errs.length }), { type: 'error', customStyle: { whiteSpace: 'pre-line' } })
}

// ---------------- 批量添加（粘贴多个名字）----------------
const bulkOpen = ref(false)
const bulk = reactive({ text: '', team_id: null })
async function saveBulk() {
  const names = bulk.text.split(/\r?\n/).map((s) => s.trim()).filter(Boolean)
  if (!names.length) return
  await api.post('/workers/bulk', { names, team_id: bulk.team_id })
  bulkOpen.value = false
  bulk.text = ''
  ElMessage.success(t('common.saved'))
  load()
}
</script>

<template>
  <div class="page">
    <div class="toolbar">
      <h1 class="page-title" style="margin: 0; flex: 1">{{ t('nav2.workers') }}</h1>
      <el-select v-model="teamFilter" clearable :placeholder="t('task.allTeams')" style="width: 130px">
        <el-option v-for="tm in auth.teams" :key="tm.id" :label="localName(tm)" :value="tm.id" />
      </el-select>
      <el-checkbox v-model="showInactive" @change="load">{{ t('workers.showInactive') }}</el-checkbox>
      <template v-if="!readonly">
        <el-button @click="download('/workers/export.xlsx', { lang: locale }, 'workers.xlsx')">{{ t('workers.export') }}</el-button>
        <el-tooltip :content="t('workers.importHint')" placement="bottom" :show-after="300">
          <el-button @click="fileInput.click()">{{ t('workers.import') }}</el-button>
        </el-tooltip>
        <input ref="fileInput" type="file" accept=".xlsx" hidden @change="importFile" />
        <el-button @click="bulk.team_id = teamFilter; bulkOpen = true">{{ t('workers.bulk') }}</el-button>
        <el-button @click="openAll">{{ t('dp.openAll') }}</el-button>
        <el-button v-if="auth.isAdmin" :icon="Plus" @click="addCol">{{ t('workers.addCol') }}</el-button>
      </template>
    </div>
    <div class="muted small">{{ readonly ? t('workers.leaderHint') : t('workers.editHint') }}</div>

    <div class="sheet-wrap">
      <table class="sheet">
        <thead>
          <tr>
            <th class="av" />
            <th class="c-name">{{ t('workers.name') }}</th>
            <th>{{ t('workers.no') }}</th>
            <th>{{ t('workers.team') }}</th>
            <th class="c-role">{{ t('workers.role') }}</th>
            <th class="c-act">{{ t('workers.active') }}</th>
            <th class="c-ops">{{ t('common.actions') }}</th>
            <th v-for="f in fields" :key="f.id" class="xcol">
              <span v-if="!auth.isAdmin" class="colhead">{{ f.label }}</span>
              <el-dropdown v-else trigger="click" @command="(c) => colCommand(f, c)">
                <span class="colhead">{{ f.label }} ▾</span>
                <template #dropdown>
                  <el-dropdown-menu>
                    <el-dropdown-item command="rename">{{ t('workers.renameCol') }}</el-dropdown-item>
                    <el-dropdown-item command="delete" divided>{{ t('workers.delCol') }}</el-dropdown-item>
                  </el-dropdown-menu>
                </template>
              </el-dropdown>
            </th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="w in shown" :key="w.id" :class="{ inactive: !w.is_active }">
            <td class="av">
              <WorkerAvatar v-if="!auth.teamOk('worker.avatar', w.team_id)" :worker="w" :size="30" />
              <el-dropdown v-else trigger="click" @command="(c) => avatarCommand(w, c)">
                <span class="avbtn"><WorkerAvatar :worker="w" :size="30" /></span>
                <template #dropdown>
                  <el-dropdown-menu>
                    <el-dropdown-item command="upload">{{ w.avatar_url ? t('avatar.change') : t('avatar.upload') }}</el-dropdown-item>
                    <el-dropdown-item v-if="w.avatar_url" command="remove">{{ t('avatar.remove') }}</el-dropdown-item>
                  </el-dropdown-menu>
                </template>
              </el-dropdown>
            </td>
            <!-- 文字格：姓名、工号、自定义列 -->
            <template v-for="key in ['name', 'employee_no']" :key="key">
              <td :class="['cell', { on: isEditing(w, key), ok: flashed === `${w.id}|${key}` }]" @click="startEdit(w, key)">
                <el-input v-if="isEditing(w, key)" v-model="editing.value" size="small" class="cell-editor" :maxlength="key === 'name' ? 100 : 50"
                          @blur="commit" @keydown="onKey" />
                <span :class="{ ghost: isEditing(w, key) }">{{ w[key] }}</span>
              </td>
            </template>
            <td :class="['cell', { on: isEditing(w, 'team_id'), ok: flashed === `${w.id}|team_id` }]" @click="startEdit(w, 'team_id')">
              <el-select v-if="isEditing(w, 'team_id')" v-model="editing.value" size="small" class="cell-editor" clearable
                         :placeholder="t('workers.noTeam')" @change="commit" @visible-change="(v) => !v && commit()">
                <el-option v-for="tm in auth.teams" :key="tm.id" :label="localName(tm)" :value="tm.id" />
              </el-select>
              <span :class="{ muted: !w.team_id, ghost: isEditing(w, 'team_id') }">{{ teamName(w.team_id) }}</span>
            </td>
            <td :class="['c-role', { ok: flashed === `${w.id}|role_id` }]">
              <span v-if="readonly">{{ roleLabel(w) }}</span>
              <el-select v-else :model-value="w.role_id ?? memberRole?.id" size="small" class="rolesel" @change="(v) => setRole(w, v)">
                <el-option v-for="r in assignableRoles" :key="r.id" :value="r.id" :label="r[`name_${locale}`]" />
              </el-select>
            </td>
            <td :class="['cell', 'c-act', { ok: flashed === `${w.id}|is_active` }]">
              <el-switch :model-value="w.is_active" size="small" :disabled="readonly" @change="(v) => { editing.id = w.id; editing.key = 'is_active'; editing.value = v; commit() }" />
            </td>
            <!-- 账号、排班放在同一格 -->
            <td class="c-ops">
              <RowActions :items="[...(canAccount(w) ? [{ label: t('acc.btn'), type: 'primary', onClick: () => openAccount(w) }] : []),
                                   ...(!readonly ? [{ label: t('ws.btn'), type: 'primary', onClick: () => openSchedule(w) }] : [])]" />
            </td>
            <td v-for="f in fields" :key="f.id" :class="['cell', { on: isEditing(w, 'x' + f.id), ok: flashed === `${w.id}|x${f.id}` }]" @click="startEdit(w, 'x' + f.id)">
              <el-input v-if="isEditing(w, 'x' + f.id)" v-model="editing.value" size="small" class="cell-editor" maxlength="500"
                        @blur="commit" @keydown="onKey" />
              <span :class="{ ghost: isEditing(w, 'x' + f.id) }">{{ w.extra?.[String(f.id)] }}</span>
            </td>
          </tr>
          <!-- 新增的一行 -->
          <tr v-if="draft" class="draft">
            <td class="av" />
            <td class="cell on"><el-input v-model="draft.name" size="small" :placeholder="t('workers.newName')" @keydown.enter="saveDraft" @keydown.esc="draft = null" /></td>
            <td class="cell on"><el-input v-model="draft.employee_no" size="small" @keydown.enter="saveDraft" /></td>
            <td class="cell on">
              <el-select v-model="draft.team_id" size="small" clearable :placeholder="t('workers.noTeam')">
                <el-option v-for="tm in auth.teams" :key="tm.id" :label="localName(tm)" :value="tm.id" />
              </el-select>
            </td>
            <td :colspan="fields.length + 3">
              <el-button size="small" type="primary" :disabled="!draft.name.trim()" @click="saveDraft">{{ t('common.save') }}</el-button>
              <el-button size="small" @click="draft = null">{{ t('common.cancel') }}</el-button>
            </td>
          </tr>
        </tbody>
      </table>
    </div>
    <el-button v-if="!readonly" class="addrow" :icon="Plus" @click="addRow">{{ t('workers.addRow') }}</el-button>

    <AccountDialog v-model="accOpen" :worker="accWorker" @saved="load" />
    <WorkerScheduleDialog v-model="wsOpen" :worker="wsWorker" @saved="load" />
    <input ref="avatarInput" type="file" accept="image/*,.heic,.heif" hidden @change="uploadAvatar" />

    <el-dialog v-model="bulkOpen" :title="t('workers.bulk')" width="min(420px, 94vw)">
      <el-form label-position="top">
        <el-form-item :label="t('workers.team')">
          <el-select v-model="bulk.team_id" clearable :placeholder="t('workers.noTeam')">
            <el-option v-for="tm in auth.teams" :key="tm.id" :label="localName(tm)" :value="tm.id" />
          </el-select>
        </el-form-item>
        <el-form-item :label="t('workers.name')">
          <el-input v-model="bulk.text" type="textarea" :rows="10" :placeholder="t('workers.bulkPh')" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="bulkOpen = false">{{ t('common.cancel') }}</el-button>
        <el-button type="primary" @click="saveBulk">{{ t('common.save') }}</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.toolbar { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; margin-bottom: 6px; }
.toolbar .el-button + .el-button { margin-left: 0; }
.muted { color: #909399; }
.small { font-size: 12px; margin-bottom: 8px; }
.sheet-wrap { overflow-x: auto; background: #fff; border-radius: 8px; }
.sheet { border-collapse: collapse; font-size: 13px; width: max-content; min-width: 100%; }
.sheet th, .sheet td { border: 1px solid #ebeef5; padding: 0 8px; height: 38px; text-align: left; white-space: nowrap; }
.sheet th { background: #f5f7fa; font-weight: 500; position: sticky; top: 0; z-index: 1; }
.sheet .av { width: 40px; text-align: center; padding: 0 4px; }
.c-name { min-width: 130px; }
.c-act { width: 60px; text-align: center !important; }
.c-ops { width: 1%; white-space: nowrap; }
.c-role { width: 120px; transition: background .4s; }
.c-role.ok { background: #e1f3d8; }
.rolesel { width: 110px; }
.xcol { min-width: 110px; }
.colhead { cursor: pointer; color: #303133; }
.colhead:hover { color: #409eff; }
.addcol { width: 1%; }
.cell { cursor: text; min-width: 90px; transition: background .4s; }
.cell:hover { background: #f5faff; }
.cell { position: relative; }
.cell.on { background: #ecf5ff; }
/* 编辑框盖在格子上（绝对定位），不改变列宽和行高，点格子时表格不会跳 */
.cell .cell-editor { position: absolute; inset: 3px 2px; width: auto; min-width: 0; }
.cell.on > span.ghost { visibility: hidden; }
.cell.ok { background: #e1f3d8; }

.avbtn { cursor: pointer; display: inline-flex; }
tr.inactive td { color: #a8abb2; }
tr.draft td { background: #fdf6ec; }
.addrow { margin-top: 8px; }
</style>
