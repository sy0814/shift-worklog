import { defineStore } from 'pinia'
import api from '../api'
import { setLang } from '../i18n'
import { clearOfflineData } from '../net'

export const useAuth = defineStore('auth', {
  state: () => ({ user: null, teams: [], lastSecret: null }), // lastSecret：刚登录时输入的密码，强制改密码页预先填好「原密码」（只在内存里）
  getters: {
    isAdmin: (s) => s.user?.role === 'admin',
    // 角色权限：scope('task.edit') → none / self / team / all；can('export') → 有没有（不是 none）
    scope: (s) => (perm) => (s.user?.role === 'admin' ? 'all' : s.user?.perms?.[perm] || 'none'),
    can: (s) => (perm) => s.user?.role === 'admin' || (s.user?.perms?.[perm] || 'none') !== 'none',
    // 本班组 + 当天合并显示的班组
    inGroup: (s) => (teamId) => s.user?.role === 'admin' || (s.user?.group_team_ids || []).includes(teamId),
    // 能不能对这个班组做某事（不涉及「自己」的权限）
    teamOk: (s) => (perm, teamId) => {
      if (s.user?.role === 'admin') return true
      const sc = s.user?.perms?.[perm] || 'none'
      return sc === 'all' || (sc === 'team' && (s.user?.group_team_ids || []).includes(teamId))
    },
    roleName: (s) => (lang) => (s.user?.role === 'admin' ? null : s.user?.role_info?.[`name_${lang}`]),
    myTeam: (s) => s.teams.find((t) => t.id === s.user?.team_id) || null,
    teamById: (s) => (id) => s.teams.find((t) => t.id === id),
  },
  actions: {
    async login(username, password) {
      const form = new URLSearchParams({ username, password })
      const { data } = await api.post('/auth/login', form)
      localStorage.setItem('token', data.access_token)
      this.user = data.user
      this.lastSecret = data.user.must_change_password ? password : null
      setLang(data.user.lang)
      await this.loadTeams()
    },
    // 班组公共账号：点自己的头像 + 个人密码
    async pinLogin(userId, pin) {
      const { data } = await api.post('/auth/pin', { user_id: userId, pin })
      localStorage.setItem('token', data.access_token)
      this.user = data.user
      this.lastSecret = data.user.must_change_password ? pin : null
      setLang(data.user.lang)
      await this.loadTeams()
    },
    async refreshMe() {
      this.user = (await api.get('/auth/me')).data
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
      localStorage.removeItem('workers_cache')
      this.lastSecret = null
      clearOfflineData()
      this.user = null
    },
  },
})
