<script setup>
import { useI18n } from 'vue-i18n'
import { LANGS, setLang } from '../i18n'
import { useAuth } from '../stores/auth'

const { locale } = useI18n()
const auth = useAuth()
const change = (code) => (auth.user ? auth.changeLang(code) : setLang(code))
</script>

<template>
  <el-select :model-value="locale" style="width: 110px" @change="change">
    <el-option v-for="l in LANGS" :key="l.code" :label="l.label" :value="l.code" />
  </el-select>
</template>
