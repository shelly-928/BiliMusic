import type { OiapiLyricData, OiapiSong } from '@/types/electron'

interface PyWebViewApi {
  minimize: () => Promise<void> | void
  maximize: () => Promise<boolean> | boolean
  close: () => Promise<void> | void
  is_maximized: () => Promise<boolean> | boolean
  toggle_fullscreen: () => Promise<boolean> | boolean
  is_fullscreen: () => Promise<boolean> | boolean
  open_external: (url: string) => Promise<void> | void
  start_drag: () => Promise<void> | void
  open_json_file?: () => Promise<string | null>
  save_json_file?: (filename: string, content: string) => Promise<string | null>
}

declare global {
  interface Window {
    pywebview?: {
      api?: PyWebViewApi
    }
  }
}

async function fetchJson<T>(url: string, init?: RequestInit): Promise<T> {
  const resp = await fetch(url, init)
  if (!resp.ok) {
    throw new Error(`HTTP ${resp.status}`)
  }
  return resp.json() as Promise<T>
}

function getPyApi(): PyWebViewApi | undefined {
  return window.pywebview?.api
}

function installFramelessDragHandlers(): void {
  const NO_DRAG_SELECTOR = [
    'button',
    'a',
    'input',
    'select',
    'textarea',
    '[role="button"]',
    '.app-titlebar__controls',
    '.now-playing-top__actions',
    '.now-playing-close',
  ].join(',')

  const isDragRegion = (target: EventTarget | null): HTMLElement | null => {
    if (!(target instanceof HTMLElement)) return null
    if (target.closest(NO_DRAG_SELECTOR)) return null
    return target.closest('.app-titlebar, .now-playing-top')
  }

  window.addEventListener('mousedown', (e) => {
    if (e.button !== 0) return
    if (!isDragRegion(e.target)) return
    getPyApi()?.start_drag?.()
  })

  window.addEventListener('dblclick', (e) => {
    if (!isDragRegion(e.target)) return
    void getPyApi()?.maximize?.()
  })
}

export function installWebBridge(): void {
  if (typeof window === 'undefined' || window.electronAPI) return

  installFramelessDragHandlers()

  const fullscreenListeners = new Set<(v: boolean) => void>()

  const notifyFullscreen = (next: boolean) => {
    fullscreenListeners.forEach((cb) => cb(next))
  }

  window.electronAPI = {
    platform: 'win32',
    minimize: () => {
      void getPyApi()?.minimize?.()
    },
    maximize: () => {
      void getPyApi()?.maximize?.()
    },
    close: () => {
      void getPyApi()?.close?.()
    },
    isMaximized: async () => {
      const res = await getPyApi()?.is_maximized?.()
      return Boolean(res)
    },
    toggleFullscreen: () => {
      Promise.resolve(getPyApi()?.toggle_fullscreen?.())
        .then((res) => notifyFullscreen(Boolean(res)))
        .catch(() => {})
    },
    isFullscreen: async () => {
      const res = await getPyApi()?.is_fullscreen?.()
      return Boolean(res)
    },
    onMaximizedChange: (callback) => {
      const handler = (event: Event) => {
        const detail = (event as CustomEvent<boolean>).detail
        callback(Boolean(detail))
      }
      window.addEventListener('bilimusic:maximized-change', handler)
      return () => window.removeEventListener('bilimusic:maximized-change', handler)
    },
    onFullscreenChange: (callback) => {
      fullscreenListeners.add(callback)
      return () => fullscreenListeners.delete(callback)
    },
    openExternal: async (url) => {
      const pyApi = getPyApi()
      if (pyApi?.open_external) {
        await pyApi.open_external(url)
      } else if (/^https?:\/\//i.test(url)) {
        window.open(url, '_blank', 'noopener,noreferrer')
      }
    },
    getAppVersion: async () => {
      try {
        const data = await fetchJson<{ version?: string }>('/api/health')
        return data.version || '0.1.0'
      } catch {
        return '0.1.0'
      }
    },
    biliApi: {
      search: (keyword, page = 1, pageSize = 20) =>
        fetchJson(`/bili-api/x/web-interface/search/type?search_type=video&keyword=${encodeURIComponent(keyword)}&page=${page}&pagesize=${pageSize}`),
      videoDetail: (bvid) =>
        fetchJson(`/bili-api/x/web-interface/view?bvid=${encodeURIComponent(bvid)}`),
      playUrl: (bvid, cid) =>
        fetchJson(`/bili-api/x/player/playurl?bvid=${encodeURIComponent(bvid)}&cid=${cid}&qn=0&fnver=0&fnval=16&fourk=1`),
      nav: () =>
        fetchJson('/bili-api/x/web-interface/nav'),
      popular: (ps = 10, pn = 1) =>
        fetchJson(`/bili-api/x/web-interface/popular?ps=${ps}&pn=${pn}`),
      recommend: (ps = 10) =>
        fetchJson(`/bili-api/x/web-interface/index/top/rcmd?ps=${ps}`),
      musicRanking: () =>
        fetchJson('/bili-api/x/web-interface/ranking/region?rid=3&day=3'),
      favorites: (mid) =>
        fetchJson(`/bili-api/x/v3/fav/folder/created/list-all?up_mid=${mid}`),
      extractAudio: async () => {
        throw new Error('Use renderer extractAudioFromVideo')
      },
      downloadAudio: async () => {
        throw new Error('Download is not enabled in lightweight mode')
      },
      qrGenerate: () => fetchJson('/api/bili/qr-generate'),
      qrPoll: (qrcodeKey) =>
        fetchJson(`/api/bili/qr-poll?qrcode_key=${encodeURIComponent(qrcodeKey)}`),
      getCookies: () => fetchJson('/api/bili/cookies'),
      logout: () => fetchJson('/api/bili/logout', { method: 'POST' }),
    },
    lyricsApi: {
      search: (keyword, page = 1, limit = 10) =>
        fetchJson<OiapiSong[]>(`/api/lyrics/search?keyword=${encodeURIComponent(keyword)}&page=${page}&limit=${limit}`),
      get: (id, format = 'lrc') =>
        fetchJson<OiapiLyricData | null>(`/api/lyrics/get?id=${encodeURIComponent(String(id))}&format=${encodeURIComponent(format)}`),
    },
  }
}
