<script setup>
// 角色权限（管理员）：每列一个角色，每行一个权限，选范围（不能 / 只限自己 / 本班组 / 全部班组）。
// 上面设角色名称、登录方式（个人账号 / 班组账号）、首页是否单独显示。改完点「保存」才生效。
import { computed, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { ElMessage, ElMessageBox } from 'element-plus'
import api from '../api'
import TriNames from '../components/TriNames.vue'
import { useAuth } from '../stores/auth'

const { t, locale } = useI18n()
const auth = useAuth()
const roles = ref([])
const defs = ref([])
const dirty = ref(new Set())

async function load() {
  const [r, d] = await Promise.all([api.get('/roles'), api.get('/roles/perms')])
  roles.value = r.data
  defs.value = d.data
  dirty.value = new Set()
}
onMounted(load)
const mark = (r) => { dirty.value = new Set([...dirty.value, r.id]) }
const name = (r) => r[`name_${locale.value}`]

async function save(r) {
  const body = { name_zh: r.name_zh, name_sr: r.name_sr, name_en: r.name_en, permissions: r.permissions,
    login_mode: r.login_mode, show_on_top: r.show_on_top }
  await api.put(`/roles/${r.id}`, body)
  ElMessage.success(t('common.saved'))
  dirty.value.delete(r.id)
  dirty.value = new Set(dirty.value)
  await auth.refreshMe() // 自己的权限可能也变了
}
async function add() {
  const { value } = await ElMessageBox.prompt(t('rp.name'), t('rp.add'), { inputValidator: (v) => !!v?.trim() })
  const n = value.trim()
  await api.post('/roles', { name_zh: n, name_sr: n, name_en: n, login_mode: 'pin', permissions: { 'task.view': 'team' } })
  load()
}
async function remove(r) {
  await ElMessageBox.confirm(t('rp.delConfirm', { n: name(r) }), t('common.delete'), { type: 'warning' })
  await api.delete(`/roles/${r.id}`)
  load()
}
const scopeType = { none: 'info', self: 'warning', team: 'primary', all: 'success' }
const rows = computed(() => defs.value.map((d) => ({ ...d })))
</script>

<template>
  <div class="page wide">
    <div class="toolbar">
      <h1 class="page-title" style="margin: 0; flex: 1">{{ t('rp.title') }}</h1>
      <el-button type="primary" @click="add">{{ t('rp.add') }}</el-button>
    </div>
    <p class="muted small">{{ t('rp.hint') }}</p>

    <div class="wrap">
      <table class="matrix">
        <thead>
          <tr>
            <th class="perm" />
            <th v-for="r in roles" :key="r.id" class="role">
              <div class="rname">
                <b>{{ name(r) }}</b>
                <el-tag v-if="r.is_builtin" size="small" effect="plain">{{ t('rp.builtin') }}</el-tag>
                <span class="muted small">{{ t('rp.people', { n: r.people }) }}</span>
              </div>
              <div class="names" @input="mark(r)"><TriNames :model-value="r" size="small" @change="mark(r)" /></div>
              <el-select v-model="r.login_mode" size="small" class="w" @change="mark(r)">
                <el-option value="password" :label="t('rp.modes.password')" />
                <el-option value="pin" :label="t('rp.modes.pin')" />
              </el-select>
              <el-checkbox v-model="r.show_on_top" size="small" @change="mark(r)">{{ t('rp.showOnTop') }}</el-checkbox>
              <div class="acts">
                <el-button size="small" type="primary" :disabled="!dirty.has(r.id)" @click="save(r)">{{ t('common.save') }}</el-button>
                <el-button v-if="!r.is_builtin" size="small" link type="danger" @click="remove(r)">{{ t('common.delete') }}</el-button>
              </div>
            </th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="d in rows" :key="d.key">
            <td class="perm">{{ t('rp.perms.' + d.key.replace('.', '_')) }}</td>
            <td v-for="r in roles" :key="r.id">
              <el-select v-model="r.permissions[d.key]" size="small" class="w" @change="mark(r)">
                <el-option v-for="s in d.scopes" :key="s" :value="s" :label="t('rp.scopes.' + s)">
                  <el-tag :type="scopeType[s]" size="small" effect="plain">{{ t('rp.scopes.' + s) }}</el-tag>
                </el-option>
              </el-select>
            </td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>
</template>

<style scoped>
.wide { max-width: 1400px; }
.toolbar { display: flex; gap: 8px; align-items: center; }
.muted { color: #909399; }
.small { font-size: 12px; }
.wrap { overflow-x: auto; background: #fff; border-radius: 8px; }
.matrix { border-collapse: collapse; font-size: 13px; width: max-content; min-width: 100%; }
.matrix th, .matrix td { border: 1px solid #ebeef5; padding: 6px 8px; vertical-align: top; text-align: left; }
.matrix thead th { background: #f5f7fa; font-weight: normal; }
.perm { position: sticky; left: 0; background: #fff; z-index: 1; min-width: 180px; }
thead .perm { background: #f5f7fa; }
.role { min-width: 190px; }
.rname { display: flex; gap: 6px; align-items: center; flex-wrap: wrap; margin-bottom: 6px; }
.names { display: flex; flex-direction: column; gap: 4px; margin-bottom: 6px; }
.w { width: 100%; }
.acts { display: flex; gap: 6px; align-items: center; margin-top: 6px; }
</style>
