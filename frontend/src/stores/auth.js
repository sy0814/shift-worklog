import { defineStore } from 'pinia'
import api from '../api'
import { localName, setLang } from '../i18n'
import { clearOfflineData } from '../net'
import { getDept, setDeptId } from '../dept'

export const useAuth = defineStore('auth', {
  // lastSecret：刚登录时输入的密码，强制改密码页预先填好「原密码」（只在内存里）
  // allTeams：所有车间的班组；teams（getter）：当前车间的班组；dept：当前车间 id；departments：所有车间
  state: () => ({ user: null, allTeams: [], departments: [], dept: getDept(), lastSecret: null }),
  getters: {
    teams: (s) => (s.departments.length > 1 ? s.allTeams.filter((t) => t.department_id === s.dept) : s.allTeams),
    // 有多个车间才显示车间（只有一个时界面和以前一样）
    multiDept: (s) => s.departments.filter((d) => d.is_active).length > 1,
    deptById: (s) => (id) => s.departments.find((d) => d.id === id),
    currentDept: (s) => s.departments.find((d) => d.id === s.dept) || null,
    canSwitchDept: (s) => !!s.user?.can_switch_dept,
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
      if (sc === 'dept') return s.allTeams.find((t) => t.id === teamId)?.department_id === s.user?.department_id
        || (s.user?.group_team_ids || []).includes(teamId)
      return sc === 'all' || (sc === 'team' && (s.user?.group_team_ids || []).includes(teamId))
    },
    // 范围是「本车间」或「全厂」（相当于管理员，可以选班组）
    wide: (s) => (perm) => s.user?.role === 'admin' || ['dept', 'all'].includes(s.user?.perms?.[perm] || 'none'),
    // 自己的班组在当前车间里（车间管理员没有班组；能切换车间的人看别的车间时也不是）
    hasOwnTeamHere: (s) => !!s.user?.team_id && s.user?.role !== 'admin'
      && (s.departments.length <= 1 || s.allTeams.find((t) => t.id === s.user.team_id)?.department_id === s.dept),
    // 按车间的权限（员工名册、班组管理、AI 分析……）能不能管当前车间
    deptOk: (s) => (perm) => {
      if (s.user?.role === 'admin') return true
      const sc = s.user?.perms?.[perm] || 'none'
      return sc === 'all' || (sc === 'dept' && s.user?.department_id === s.dept)
    },
    roleName: (s) => (lang) => (s.user?.role === 'admin' ? null : s.user?.role_info?.[`name_${lang}`]),
    myTeam: (s) => s.teams.find((t) => t.id === s.user?.team_id) || null,
    teamById: (s) => (id) => s.allTeams.find((t) => t.id === id),
    // 班组名；别的车间的班组前面加上车间名（跨车间移交时看得出来）
    teamLabel: (s) => (id) => {
      const tm = s.allTeams.find((t) => t.id === id)
      if (!tm) return ''
      const d = s.departments.length > 1 && tm.department_id !== s.dept ? s.departments.find((x) => x.id === tm.department_id) : null
      return d ? `${localName(d)} · ${localName(tm)}` : localName(tm)
    },
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
      const [teams, deps] = await Promise.all([api.get('/teams'), api.get('/departments', { silent: true }).catch(() => null)])
      this.allTeams = teams.data
      if (deps) this.departments = deps.data.departments
      this.fixDept()
    },
    /** 当前车间：不能切换的人永远是自己的车间；能切换的人用上次选的（没有就用自己的 / 第一个） */
    fixDept() {
      const ok = (id) => this.departments.some((d) => d.id === id)
      let d = this.dept
      if (this.user && (!this.user.can_switch_dept || !ok(d))) d = this.user.department_id ?? null
      if (!ok(d)) d = this.departments.find((x) => x.is_active)?.id ?? this.departments[0]?.id ?? null
      if (d !== this.dept) this.setDept(d)
    },
    setDept(id) {
      this.dept = id
      setDeptId(id)
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
