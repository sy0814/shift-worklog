import { defineStore } from 'pinia'
import api from '../api'
import { setLang } from '../i18n'

export const useAuth = defineStore('auth', {
  state: () => ({ user: null, teams: [] }),
  getters: {
    isAdmin: (s) => s.user?.role === 'admin',
    myTeam: (s) => s.teams.find((t) => t.id === s.user?.team_id) || null,
    teamById: (s) => (id) => s.teams.find((t) => t.id === id),
  },
  actions: {
    async login(username, password) {
      const form = new URLSearchParams({ username, password })
      const { data } = await api.post('/auth/login', form)
      localStorage.setItem('token', data.access_token)
      this.user = data.user
      setLang(data.user.lang)
      await this.loadTeams()
    },
    async restore() {
      if (this.user || !localStorage.getItem('token')) return !!this.user
      try {
        const { data } = await api.get('/auth/me')
        this.user = data
        setLang(data.lang)
        await this.loadTeams()
        return true
      } catch {
        return false
      }
    },
    async loadTeams() {
      this.teams = (await api.get('/teams')).data
    },
    async changeLang(code) {
      setLang(code)
      if (this.user) this.user = (await api.patch('/auth/me', { lang: code })).data
    },
    logout() {
      // 离线草稿按用户保存在本机，退出登录不会删除，下次同一账号登录后继续同步
      localStorage.removeItem('token')
      this.user = null
    },
  },
})
