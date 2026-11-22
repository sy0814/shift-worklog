/* Service Worker：离线也能打开页面，并显示最后一次联网时的数据。
 * - 页面和静态文件：预缓存，断网直接打开
 * - 数据接口 GET /api/*：优先联网（5 秒超时），失败时用缓存，并加上 X-From-Cache 头让页面提示「离线数据」
 * - 图片 /api/files/*：按文件路径缓存（忽略每次都会变的签名参数），图片本身不会变
 * - 所有写操作（POST/PUT/PATCH/DELETE）一律不缓存；离线新建由页面的发件箱（IndexedDB）负责
 */
import { cleanupOutdatedCaches, createHandlerBoundToURL, precacheAndRoute } from 'workbox-precaching'
import { NavigationRoute, registerRoute } from 'workbox-routing'
import { CacheFirst, NetworkFirst } from 'workbox-strategies'
import { ExpirationPlugin } from 'workbox-expiration'
import { CacheableResponsePlugin } from 'workbox-cacheable-response'

cleanupOutdatedCaches()
precacheAndRoute(self.__WB_MANIFEST)

// 单页应用：所有页面地址都返回 index.html（接口地址除外）
registerRoute(new NavigationRoute(createHandlerBoundToURL('/index.html'), { denylist: [/^\/api\//] }))

// 不缓存的接口：登录、导出、模板下载
const NO_CACHE = [/^\/api\/auth\/login/, /^\/api\/export\//, /^\/api\/attendance\/template/, /^\/api\/glossary\/export/]

const markFromCache = {
  // 从缓存拿出来的响应加个标记头（带上缓存时间）
  cachedResponseWillBeUsed: async ({ cachedResponse }) => {
    if (!cachedResponse) return cachedResponse
    const headers = new Headers(cachedResponse.headers)
    headers.set('X-From-Cache', headers.get('X-Cached-At') || '1')
    const body = await cachedResponse.blob()
    return new Response(body, { status: cachedResponse.status, statusText: cachedResponse.statusText, headers })
  },
  cacheWillUpdate: async ({ response }) => {
    if (!response || response.status !== 200) return null
    const headers = new Headers(response.headers)
    headers.set('X-Cached-At', new Date().toISOString())
    const body = await response.clone().blob()
    return new Response(body, { status: 200, statusText: response.statusText, headers })
  },
}

registerRoute(
  ({ url, request }) => request.method === 'GET' && url.pathname.startsWith('/api/')
    && !url.pathname.startsWith('/api/files/') && !NO_CACHE.some((r) => r.test(url.pathname)),
  new NetworkFirst({
    cacheName: 'api',
    networkTimeoutSeconds: 5,
    plugins: [markFromCache, new ExpirationPlugin({ maxEntries: 300, maxAgeSeconds: 7 * 24 * 3600 })],
  }),
)

registerRoute(
  ({ url, request }) => request.method === 'GET' && url.pathname.startsWith('/api/files/'),
  new CacheFirst({
    cacheName: 'photos',
    plugins: [
      { cacheKeyWillBeUsed: async ({ request }) => { const u = new URL(request.url); u.search = ''; return u.href } },
      new CacheableResponsePlugin({ statuses: [200] }),
      new ExpirationPlugin({ maxEntries: 400, maxAgeSeconds: 30 * 24 * 3600, purgeOnQuotaError: true }),
    ],
  }),
)

// 页面通知：有新版本时由页面决定何时刷新（避免冲掉正在填的表单）
self.addEventListener('message', (e) => {
  if (e.data?.type === 'SKIP_WAITING') self.skipWaiting()
  if (e.data?.type === 'CLEAR_DATA') e.waitUntil(Promise.all([caches.delete('api'), caches.delete('photos')]))
})
