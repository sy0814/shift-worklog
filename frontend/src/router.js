import { createRouter, createWebHistory } from 'vue-router'
import api from './api'
import { getDept } from './dept'
import { useAuth } from './stores/auth'

const routes = [
  { path: '/login', name: 'login', component: () => import('./views/Login.vue'), meta: { public: true } },
  { path: '/portal', name: 'portal', component: () => import('./views/Portal.vue'), meta: { public: true } }, // 全厂导航（多个车间时）
  { path: '/change-password', name: 'change-password', component: () => import('./views/ChangePassword.vue') },
  {
    path: '/',
    component: () => import('./views/Layout.vue'),
    children: [
      { path: '', name: 'home', component: () => import('./views/Home.vue') },
      { path: 'board', redirect: '/' }, // 交接班已合并到首页
      { path: 'tasks', name: 'tasks', component: () => import('./views/Tasks.vue') },
      { path: 'projects', name: 'projects', component: () => import('./views/Projects.vue') },
      { path: 'equipment', name: 'equipment', component: () => import('./views/Equipment.vue') },
      { path: 'attendance', name: 'attendance', component: () => import('./views/Attendance.vue') },
      { path: 'schedule', name: 'schedule', component: () => import('./views/Schedule.vue') },
      { path: 'users', name: 'users', component: () => import('./views/Users.vue'), meta: { admin: true } },
      { path: 'workers', name: 'workers', component: () => import('./views/Workers.vue'), meta: { perms: ['worker.pin', 'worker.manage'] } },
      { path: 'roles', name: 'roles', component: () => import('./views/Roles.vue'), meta: { admin: true } },
      { path: 'glossary', name: 'glossary', component: () => import('./views/Glossary.vue'), meta: { admin: true } },
      { path: 'inspections', redirect: { name: 'projects', query: { tab: 'inspections' } } }, // 定期巡查已并入「项目」页
      { path: 'analysis', name: 'analysis', component: () => import('./views/Analysis.vue'), meta: { perms: ['analysis'] } },
      { path: 'settings', name: 'settings', component: () => import('./views/Settings.vue'), meta: { admin: true } },
      { path: 'audit', name: 'audit', component: () => import('./views/Audit.vue'), meta: { admin: true } },
    ],
  },
  { path: '/:p(.*)*', redirect: '/' },
]

const router = createRouter({ history: createWebHistory(), routes })

/** 没登录时：有多个车间、本机还没选过车间 → 先去导航页 */
async function needPortal(auth) {
  if (getDept()) return false
  try {
    if (!auth.departments.length) auth.departments = (await api.get('/departments', { silent: true })).data.departments
  } catch {
    return false
  }
  return auth.multiDept
}

router.beforeEach(async (to) => {
  if (to.meta.public) return true
  const auth = useAuth()
  if (!(await auth.restore())) {
    if (await needPortal(auth)) return { name: 'portal' }
    return { name: 'login', query: { next: to.fullPath } }
  }
  // 用默认密码 / 别人重设的密码登录：先改密码
  if (auth.user?.must_change_password && to.name !== 'change-password') return { name: 'change-password', query: { next: to.fullPath } }
  if (to.name === 'change-password' && !auth.user?.must_change_password) return { name: 'home' }
  if (to.meta.admin && !auth.isAdmin) return { name: 'home' }
  if (to.meta.perm && !auth.can(to.meta.perm)) return { name: 'home' }
  if (to.meta.perms && !to.meta.perms.some((p) => auth.can(p))) return { name: 'home' }
  return true
})

export default router
