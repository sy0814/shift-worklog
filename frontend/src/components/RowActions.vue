<script setup>
// 表格「操作」格子：items = [{ label, type: 'primary' | 'success' | 'danger' | '', onClick }]（不显示的别放进来）。
// 电脑：全部排一行；手机：前 keep 个直接显示，其余收进「⋯」下拉（删除放最后、前面加分隔线）。
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { narrowKeep, useNarrow } from '../rowActions'

const props = defineProps({ items: { type: Array, required: true }, keep: { type: Number, default: 2 } })
const { t } = useI18n()
const narrow = useNarrow()
const shown = computed(() => (narrow.value ? props.items.slice(0, narrowKeep(props.items.map((a) => a.label), props.keep)) : props.items))
const rest = computed(() => props.items.slice(shown.value.length))
const run = (i) => rest.value[i]?.onClick()
</script>

<template>
  <div class="row-actions">
    <el-button v-for="(a, i) in shown" :key="i" link :type="a.type || ''" @click.stop="a.onClick()">{{ a.label }}</el-button>
    <el-dropdown v-if="rest.length" trigger="click" @command="run">
      <el-button link class="more" :aria-label="t('menu.more')" @click.stop>⋯</el-button>
      <template #dropdown>
        <el-dropdown-menu>
          <el-dropdown-item v-for="(a, i) in rest" :key="i" :command="i" :divided="a.type === 'danger' && i > 0"
                            :class="{ danger: a.type === 'danger' }">{{ a.label }}</el-dropdown-item>
        </el-dropdown-menu>
      </template>
    </el-dropdown>
  </div>
</template>

<style scoped>
.row-actions { display: flex; align-items: center; gap: 12px; white-space: nowrap; flex-wrap: nowrap; }
.row-actions :deep(.el-button + .el-button) { margin-left: 0; }
.more { font-size: 18px; letter-spacing: 1px; padding: 0 2px; }
:global(.el-dropdown-menu__item.danger) { color: var(--el-color-danger); }
</style>
