<script setup>
// AI 工作量分析（管理员）：发起分析、历史报告、报告正文 + 统计数据（供核对）
import { computed, onMounted, onUnmounted, reactive, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { marked } from 'marked'
import DOMPurify from 'dompurify'
import dayjs from 'dayjs'
import api from '../api'
import { LANGS, localName } from '../i18n'
import { fmtFull } from '../format'
import { useAuth } from '../stores/auth'

const { t, locale } = useI18n()
const auth = useAuth()

const form = reactive({
  range: [dayjs().subtract(1, 'month').startOf('month').format('YYYY-MM-DD'), dayjs().subtract(1, 'month').endOf('month').format('YYYY-MM-DD')],
  team_id: null,
  lang: locale.value,
})
const configured = ref(true)
const list = ref([])
const current = ref(null)
const starting = ref(false)

async function loadList() {
  list.value = (await api.get('/analysis')).data
}
async function open(id) {
  current.value = (await api.get(`/analysis/${id}`)).data
  poll()
}
onMounted(async () => {
  configured.value = (await api.get('/settings/llm')).data.api_key_set
  await loadList()
  if (list.value.length) open(list.value[0].id)
})

async function start() {
  starting.value = true
  try {
    const { data } = await api.post('/analysis', { start: form.range[0], end: form.range[1], team_id: form.team_id, lang: form.lang })
    await loadList()
    await open(data.id)
  } finally {
    starting.value = false
  }
}
async function retry() {
  await api.post(`/analysis/${current.value.id}/retry`)
  await open(current.value.id)
}

// 分析中：每 3 秒刷新
let timer = null
function poll() {
  clearTimeout(timer)
  if (!current.value || !['pending', 'running'].includes(current.value.status)) return
  timer = setTimeout(async () => {
    const id = current.value.id
    const fresh = (await api.get(`/analysis/${id}`)).data
    if (current.value?.id === id) current.value = fresh
    if (!['pending', 'running'].includes(fresh.status)) loadList()
    poll()
  }, 3000)
}
onUnmounted(() => clearTimeout(timer))

// 模型输出转 HTML，并清洗掉脚本等危险内容
const html = computed(() => current.value?.report_md ? DOMPurify.sanitize(marked.parse(current.value.report_md)) : '')
const teamLabel = (id) => (id ? localName(auth.teamById(id)) : t('ai.allTeams'))
const statusType = { pending: 'info', running: 'warning', done: 'success', failed: 'danger' }

function downloadMd() {
  const r = current.value
  const blob = new Blob([`# ${t('ai.title')} ${r.start} ~ ${r.end} · ${teamLabel(r.team_id)}\n\n${r.report_md}\n`], { type: 'text/markdown;charset=utf-8' })
  const a = document.createElement('a')
  a.href = URL.createObjectURL(blob)
  a.download = `ai-report-${r.start}_${r.end}.md`
  a.click()
  setTimeout(() => URL.revokeObjectURL(a.href), 1000)
}
const printReport = () => window.print()
const fmtNum = (v) => (v == null ? '—' : v)
const perMember = (p) => (p ? `${p.min} / ${p.median} / ${p.max}` : '—')
</script>

<template>
  <div class="page">
    <h1 class="page-title">{{ t('ai.title') }}</h1>
    <el-alert v-if="!configured" type="error" :title="t('ai.notConfigured')" :closable="false" show-icon class="mb" />

    <el-card shadow="never" class="mb no-print">
      <div class="form">
        <el-date-picker v-model="form.range" type="daterange" value-format="YYYY-MM-DD" unlink-panels :clearable="false" style="max-width: 280px" />
        <el-select v-model="form.team_id" clearable :placeholder="t('ai.allTeams')" style="width: 140px">
          <el-option v-for="tm in auth.teams" :key="tm.id" :label="localName(tm)" :value="tm.id" />
        </el-select>
        <el-radio-group v-model="form.lang">
          <el-radio-button v-for="l in LANGS" :key="l.code" :value="l.code">{{ l.label }}</el-radio-button>
        </el-radio-group>
        <el-button type="primary" :loading="starting" :disabled="!configured || !form.range" @click="start">{{ t('ai.start') }}</el-button>
      </div>
    </el-card>

    <div class="cols">
      <aside class="history no-print">
        <h4>{{ t('ai.history') }}</h4>
        <div v-if="!list.length" class="muted">{{ t('ai.empty') }}</div>
        <div v-for="r in list" :key="r.id" :class="['hitem', { active: current?.id === r.id }]" @click="open(r.id)">
          <div><b>{{ r.start.slice(5) }} ~ {{ r.end.slice(5) }}</b> · {{ teamLabel(r.team_id) }}</div>
          <div class="muted small">
            <el-tag :type="statusType[r.status]" size="small">{{ t(`ai.st.${r.status}`) }}</el-tag>
            {{ fmtFull(r.created_at) }} · {{ r.lang }}
          </div>
        </div>
      </aside>

      <section v-if="current" class="report">
        <div class="rhead">
          <div>
            <b>{{ current.start }} ~ {{ current.end }} · {{ teamLabel(current.team_id) }}</b>
            <div class="muted small">
              {{ t('ai.by', { name: current.created_by_name }) }} · {{ fmtFull(current.created_at) }} · <code>{{ current.model }}</code>
              <template v-if="current.usage?.prompt_tokens"> · {{ t('ai.tokens', { i: current.usage.prompt_tokens, o: current.usage.completion_tokens }) }}</template>
            </div>
          </div>
          <div v-if="current.status === 'done'" class="no-print btns">
            <el-button size="small" @click="downloadMd">{{ t('ai.download') }}</el-button>
            <el-button size="small" @click="printReport">{{ t('ai.print') }}</el-button>
          </div>
        </div>

        <el-alert v-if="['pending', 'running'].includes(current.status)" type="info" :closable="false" show-icon :title="t('ai.running')" class="mb" />
        <el-alert v-if="current.status === 'failed'" type="error" :closable="false" show-icon :title="t('ai.failed')" :description="current.error" class="mb">
        </el-alert>
        <el-button v-if="current.status === 'failed'" class="mb no-print" @click="retry">{{ t('ai.retry') }}</el-button>

        <!-- eslint-disable-next-line vue/no-v-html  已用 DOMPurify 清洗 -->
        <article v-if="html" class="md" v-html="html" />

        <el-collapse v-if="current.stats" class="mt">
          <el-collapse-item :title="t('ai.stats')" name="s">
            <p class="muted small">{{ t('ai.note') }}</p>
            <h4>{{ t('ai.teams') }}</h4>
            <el-table :data="current.stats.teams" size="small" border>
              <el-table-column prop="team" :label="t('ai.col.team')" width="110" fixed />
              <el-table-column prop="tasks" :label="t('ai.col.tasks')" width="70" />
              <el-table-column :label="t('ai.col.done')" width="70"><template #default="{ row }">{{ row.by_status.done }}</template></el-table-column>
              <el-table-column :label="t('ai.col.open')" width="80"><template #default="{ row }">{{ row.by_status.not_started + row.by_status.in_progress }}</template></el-table-column>
              <el-table-column prop="handovers_out" :label="t('ai.col.hoOut')" width="70" />
              <el-table-column prop="handovers_in" :label="t('ai.col.hoIn')" width="70" />
              <el-table-column prop="open_overdue" :label="t('ai.col.overdue')" width="90" />
              <el-table-column :label="t('ai.col.avgH')" width="90"><template #default="{ row }">{{ fmtNum(row.avg_task_hours_done) }}</template></el-table-column>
              <el-table-column prop="tasks_without_workers" :label="t('ai.col.noWorkers')" width="100" />
              <el-table-column prop="members" :label="t('ai.col.members')" width="70" />
              <el-table-column :label="t('ai.col.perMember')" min-width="170"><template #default="{ row }">{{ perMember(row.tasks_per_member) }}</template></el-table-column>
              <el-table-column :label="t('ai.col.idle')" min-width="160"><template #default="{ row }">{{ row.members_present_but_no_tasks.join('、') }}</template></el-table-column>
            </el-table>
            <h4>{{ t('ai.people') }}</h4>
            <el-table :data="current.stats.people" size="small" border max-height="480">
              <el-table-column prop="name" :label="t('ai.col.name')" width="140" fixed />
              <el-table-column prop="team" :label="t('ai.col.team')" width="100" />
              <el-table-column prop="scheduled_shifts" :label="t('ai.col.sched')" width="90" />
              <el-table-column prop="present_shifts" :label="t('ai.col.present')" width="90" />
              <el-table-column prop="leave" :label="t('ai.col.leave')" width="65" />
              <el-table-column prop="sick" :label="t('ai.col.sick')" width="65" />
              <el-table-column prop="absent" :label="t('ai.col.absent')" width="65" />
              <el-table-column prop="cover_shifts_for_other_teams" :label="t('ai.col.cover')" width="65" />
              <el-table-column prop="tasks" :label="t('ai.col.tasks')" width="65" />
              <el-table-column prop="done" :label="t('ai.col.done')" width="65" />
              <el-table-column prop="open" :label="t('ai.col.open')" width="75" />
              <el-table-column prop="handed_over" :label="t('ai.col.ho')" width="75" />
              <el-table-column prop="task_hours" :label="t('ai.col.hours')" width="70" />
              <el-table-column :label="t('ai.col.hps')" width="90"><template #default="{ row }">{{ fmtNum(row.hours_per_present_shift) }}</template></el-table-column>
              <el-table-column prop="open_overdue" :label="t('ai.col.overdue')" width="90" />
            </el-table>
          </el-collapse-item>
        </el-collapse>
      </section>
    </div>
  </div>
</template>

<style scoped>
.mb { margin-bottom: 12px; }
.mt { margin-top: 16px; }
.form { display: flex; gap: 10px; flex-wrap: wrap; align-items: center; }
.cols { display: grid; grid-template-columns: 240px 1fr; gap: 16px; align-items: start; }
@media (max-width: 900px) { .cols { grid-template-columns: 1fr; } }
.history { background: #fff; border-radius: 8px; padding: 8px 12px; }
.history h4 { margin: 4px 0 8px; }
.hitem { padding: 8px; border-radius: 6px; cursor: pointer; border-bottom: 1px solid #f2f3f5; font-size: 13px; }
.hitem:hover { background: #f5f7fa; }
.hitem.active { background: #ecf5ff; }
.report { background: #fff; border-radius: 8px; padding: 16px; min-width: 0; }
.rhead { display: flex; justify-content: space-between; gap: 12px; align-items: flex-start; margin-bottom: 12px; flex-wrap: wrap; }
.btns { display: flex; gap: 6px; }
.muted { color: #909399; }
.small { font-size: 12px; }
code { background: #f4f4f5; padding: 1px 4px; border-radius: 3px; }
.md { line-height: 1.7; font-size: 14px; overflow-x: auto; }
.md :deep(h1), .md :deep(h2) { font-size: 18px; margin: 18px 0 8px; border-bottom: 1px solid #ebeef5; padding-bottom: 4px; }
.md :deep(h3) { font-size: 15px; margin: 14px 0 6px; }
.md :deep(table) { border-collapse: collapse; margin: 8px 0; font-size: 13px; }
.md :deep(th), .md :deep(td) { border: 1px solid #dcdfe6; padding: 4px 8px; text-align: left; }
.md :deep(th) { background: #f5f7fa; }
.md :deep(ul), .md :deep(ol) { padding-left: 22px; }
@media print {
  .no-print { display: none !important; }
  .cols { grid-template-columns: 1fr; }
}
</style>
