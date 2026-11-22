import { createRouter, createWebHistory } from 'vue-router'
import { useAuth } from './stores/auth'

const routes = [
  { path: '/login', name: 'login', component: () => import('./views/Login.vue'), meta: { public: true } },
  {
    path: '/',
    component: () => import('./views/Layout.vue'),
    children: [
      { path: '', name: 'home', component: () => import('./views/Home.vue') },
      { path: 'board', name: 'board', component: () => import('./views/Board.vue') },
      { path: 'tasks', name: 'tasks', component: () => import('./views/Tasks.vue') },
      { path: 'attendance', name: 'attendance', component: () => import('./views/Attendance.vue') },
      { path: 'schedule', name: 'schedule', component: () => import('./views/Schedule.vue') },
      { path: 'users', name: 'users', component: () => import('./views/Users.vue'), meta: { admin: true } },
      { path: 'workers', name: 'workers', component: () => import('./views/Workers.vue'), meta: { admin: true } },
      { path: 'glossary', name: 'glossary', component: () => import('./views/Glossary.vue'), meta: { admin: true } },
      { path: 'inspections', name: 'inspections', component: () => import('./views/Inspections.vue'), meta: { admin: true } },
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
  return true
})

export default router
