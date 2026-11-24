<script setup>
import { computed, watchEffect } from 'vue'
import { useI18n } from 'vue-i18n'
import { elementLocales } from './i18n'
import { appTitle, loadBranding } from './branding'

const { locale } = useI18n()
const elLocale = computed(() => elementLocales[locale.value])
loadBranding()
watchEffect(() => { document.title = appTitle(locale.value) }) // 浏览器标签页上的名称
</script>

<template>
  <el-config-provider :locale="elLocale">
    <router-view />
  </el-config-provider>
</template>
