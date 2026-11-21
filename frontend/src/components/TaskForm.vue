<script setup>
// 新建 / 编辑任务。新建时图片随任务一起进离线发件箱；编辑时只改文字和人员，图片在详情里补充。
import { computed, reactive, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { ElMessage } from 'element-plus'
import dayjs from 'dayjs'
import api from '../api'
import { localName } from '../i18n'
import { isNarrow } from '../format'
import { uuid } from '../offline'
import { preparePhotos } from '../photo'
import { useAuth } from '../stores/auth'
import { useOutbox } from '../stores/outbox'
import LocalPhotos from './LocalPhotos.vue'
import PhotoPicker from './PhotoPicker.vue'

const props = defineProps({ task: { type: Object, default: null } })
const visible = defineModel({ type: Boolean })
const emit = defineEmits(['saved'])
const { t, locale } = useI18n()
const auth = useAuth()
const outbox = useOutbox()

const workers = ref([])
const form = reactive({})
const photos = ref([])
const saving = ref(false)
let original = {}

const DT = 'YYYY-MM-DDTHH:mm:ssZ'
const toLocal = (iso) => (iso ? dayjs(iso).format(DT) : null)

/** 编辑时显示当前语言的文字（有译文用译文，否则原文），并记住这段文字属于哪种语言 */
function pick(tri, src) {
  if (tri?.[locale.value]) return { text: tri[locale.value], lang: locale.value }
  return { text: (src && tri?.[src]) || '', lang: src || locale.value }
}

async function init() {
  // 先重置表单（新的 client_id），再加载员工名单；断网时用本机缓存的名单
  photos.value = []
  const tk = props.task
  if (tk) {
    const c = pick(tk.content, tk.source_lang)
    const l = pick(tk.leftover, tk.leftover_source_lang)
    original = {
      content: c.text, contentLang: c.lang, leftover: l.text, leftoverLang: l.lang,
      worker_ids: tk.workers.map((w) => w.id), start_at: toLocal(tk.start_at), end_at: toLocal(tk.end_at),
    }
    Object.assign(form, { ...original, worker_ids: [...original.worker_ids] })
  } else {
    Object.assign(form, {
      client_id: uuid(), content: '', leftover: '', worker_ids: [], status: 'not_started',
      start_at: null, end_at: null, team_id: auth.user.team_id ?? auth.teams[0]?.id,
    })
  }
  workers.value = await loadWorkers()
}

async function loadWorkers() {
  try {
    const list = (await api.get('/workers', { silent: true })).data
    try { localStorage.setItem('workers_cache', JSON.stringify(list)) } catch { /* 存不下就算了 */ }
    return list
  } catch {
    try { return JSON.parse(localStorage.getItem('workers_cache')) || [] } catch { return [] }
  }
}
watch(visible, (v) => v && init(), { immediate: true })

// 参与人员按班组分组，本班组排最前
const workerGroups = computed(() => {
  const myTeam = props.task?.team_id ?? form.team_id
  const groups = new Map()
  for (const w of workers.value) {
    if (!groups.has(w.team_id)) groups.set(w.team_id, [])
    groups.get(w.team_id).push(w)
  }
  // 编辑时保留已停用但仍在任务里的人
  for (const w of props.task?.workers || []) {
    if (!workers.value.some((x) => x.id === w.id)) {
      if (!groups.has(w.team_id)) groups.set(w.team_id, [])
      groups.get(w.team_id).push(w)
    }
  }
  return [...groups.entries()]
    .sort(([a], [b]) => (a === myTeam ? -1 : b === myTeam ? 1 : (a ?? 999) - (b ?? 999)))
    .map(([tid, list]) => ({ label: tid ? localName(auth.teamById(tid)) : t('workers.noTeam'), list }))
})

const fullscreen = isNarrow()
const preparing = ref(false)
async function addPhotos(files) {
  preparing.value = true
  try {
    photos.value.push(...(await preparePhotos(files)))
  } finally {
    preparing.value = false
  }
}

async function save() {
  if (!form.content?.trim()) return
  if (form.start_at && form.end_at && form.end_at < form.start_at) return
  saving.value = true
  try {
    if (props.task) await saveEdit()
    else await saveNew()
  } finally {
    saving.value = false
  }
}

async function saveNew() {
  const body = {
    client_id: form.client_id, content: form.content.trim(), lang: locale.value,
    worker_ids: form.worker_ids, status: form.status, start_at: form.start_at || null,
    end_at: form.end_at || null, leftover: form.leftover?.trim() || null,
    recorded_at: new Date().toISOString(),
    ...(auth.isAdmin ? { team_id: form.team_id } : {}),
  }
  const task = await outbox.submitTask(body, photos.value)
  visible.value = false
  if (task) {
    ElMessage.success(t('task.created'))
    emit('saved', task)
  } else {
    ElMessage.warning({ message: t('outbox.savedOffline'), duration: 5000 })
  }
}

async function saveEdit() {
  const o = original
  const patch = {}
  if (form.content.trim() !== o.content) Object.assign(patch, { content: form.content.trim(), lang: o.contentLang })
  if ((form.leftover || '').trim() !== (o.leftover || '')) {
    patch.leftover = form.leftover.trim()
    patch.leftover_lang = o.leftover ? o.leftoverLang : locale.value
  }
  if ([...form.worker_ids].sort().join() !== [...o.worker_ids].sort().join()) patch.worker_ids = form.worker_ids
  if (form.start_at !== o.start_at) patch.start_at = form.start_at || null
  if (form.end_at !== o.end_at) patch.end_at = form.end_at || null
  if (Object.keys(patch).length) await api.patch(`/tasks/${props.task.id}`, patch)
  visible.value = false
  ElMessage.success(t('common.saved'))
  emit('saved', props.task)
}
</script>

<template>
  <el-dialog v-model="visible" :title="task ? t('task.edit') : t('task.new')" :fullscreen="fullscreen"
             width="min(640px, 96vw)" :close-on-click-modal="false" append-to-body>
    <el-form label-position="top" @submit.prevent>
      <el-form-item v-if="!task && auth.isAdmin" :label="t('task.team')">
        <el-select v-model="form.team_id">
          <el-option v-for="tm in auth.teams" :key="tm.id" :label="localName(tm)" :value="tm.id" />
        </el-select>
      </el-form-item>
      <el-form-item :label="t('task.content')" required>
        <el-input v-model="form.content" type="textarea" :autosize="{ minRows: 3, maxRows: 10 }"
                  :placeholder="t('task.contentPh')" maxlength="5000" />
      </el-form-item>
      <el-form-item :label="t('task.workers')">
        <el-select v-model="form.worker_ids" multiple filterable :placeholder="t('task.noWorkers')" style="width: 100%">
          <el-option-group v-for="g in workerGroups" :key="g.label" :label="g.label">
            <el-option v-for="w in g.list" :key="w.id" :label="w.name" :value="w.id" />
          </el-option-group>
        </el-select>
      </el-form-item>
      <el-form-item v-if="!task" :label="t('task.status')">
        <el-radio-group v-model="form.status">
          <el-radio-button v-for="s in ['not_started', 'in_progress', 'done']" :key="s" :value="s">{{ t(`status.${s}`) }}</el-radio-button>
        </el-radio-group>
      </el-form-item>
      <div class="two">
        <el-form-item :label="t('task.start')">
          <el-date-picker v-model="form.start_at" type="datetime" :value-format="DT" format="MM-DD HH:mm" style="width: 100%" />
        </el-form-item>
        <el-form-item :label="t('task.end')" :error="form.start_at && form.end_at && form.end_at < form.start_at ? '< ' + t('task.start') : ''">
          <el-date-picker v-model="form.end_at" type="datetime" :value-format="DT" format="MM-DD HH:mm" style="width: 100%" />
        </el-form-item>
      </div>
      <el-form-item :label="t('task.leftover')">
        <el-input v-model="form.leftover" type="textarea" :autosize="{ minRows: 2, maxRows: 6 }" maxlength="5000" />
      </el-form-item>
      <el-form-item v-if="!task" :label="t('photo.title')">
        <PhotoPicker @pick="addPhotos" />
        <LocalPhotos v-loading="preparing" :photos="photos" @remove="(i) => photos.splice(i, 1)" />
      </el-form-item>
    </el-form>
    <template #footer>
      <el-button @click="visible = false">{{ t('common.cancel') }}</el-button>
      <el-button type="primary" :loading="saving || preparing" :disabled="!form.content?.trim()" @click="save">{{ t('common.save') }}</el-button>
    </template>
  </el-dialog>
</template>

<style scoped>
.two { display: grid; grid-template-columns: 1fr 1fr; gap: 0 12px; }
@media (max-width: 480px) { .two { grid-template-columns: 1fr; } }
</style>
