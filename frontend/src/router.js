import { createRouter, createWebHistory } from 'vue-router'
import { useAuth } from './stores/auth'

const routes = [
  { path: '/login', name: 'login', component: () => import('./views/Login.vue'), meta: { public: true } },
  {
    path: '/',
    component: () => import('./views/Layout.vue'),
    children: [
      { path: '', name: 'home', component: () => import('./views/Home.vue') },
      { path: 'board', redirect: '/' }, // 交接班已合并到首页
      { path: 'tasks', name: 'tasks', component: () => import('./views/Tasks.vue') },
      { path: 'projects', name: 'projects', component: () => import('./views/Projects.vue') },
      { path: 'attendance', name: 'attendance', component: () => import('./views/Attendance.vue') },
      { path: 'schedule', name: 'schedule', component: () => import('./views/Schedule.vue') },
      { path: 'users', name: 'users', component: () => import('./views/Users.vue'), meta: { admin: true } },
      { path: 'workers', name: 'workers', component: () => import('./views/Workers.vue'), meta: { perm: 'worker.pin' } },
      { path: 'roles', name: 'roles', component: () => import('./views/Roles.vue'), meta: { admin: true } },
      { path: 'glossary', name: 'glossary', component: () => import('./views/Glossary.vue'), meta: { admin: true } },
      { path: 'inspections', redirect: { name: 'projects', query: { tab: 'inspections' } } }, // 定期巡查已并入「项目」页
      { path: 'analysis', name: 'analysis', component: () => import('./views/Analysis.vue'), meta: { admin: true } },
      { path: 'settings', name: 'settings', component: () => import('./views/Settings.vue'), meta: { admin: true } },
      { path: 'audit', name: 'audit', component: () => import('./views/Audit.vue'), meta: { admin: true } },
    ],
  },
  { path: '/:p(.*)*', redirect: '/' },
]

const router = createRouter({ history: createWebHistory(), routes })

router.beforeEach(async (to) => {
  if (to.meta.public) return true
  const auth = useAuth()
  if (!(await auth.restore())) return { name: 'login', query: { next: to.fullPath } }
  if (to.meta.admin && !auth.isAdmin) return { name: 'home' }
  if (to.meta.perm && !auth.can(to.meta.perm)) return { name: 'home' }
  return true
})

export default router
