import { createContext, useContext, useState, useCallback, useMemo, useRef, useEffect, type ReactNode } from 'react'
import type { Track, RepeatMode } from '@/types'
import { toggleFavoriteTrack, loadFavoriteTracks, loadRecentTracks, saveRecentTracks } from '@/utils/storage'
import { useAppSettings } from '@/hooks/useAppSettings'

interface PlayerState {
  currentTrack: Track | null
  isPlaying: boolean
  volume: number
  isMuted: boolean
  repeatMode: RepeatMode
  isShuffled: boolean
  queue: Track[]
  loadingAudio: boolean
}

interface PlayerActions {
  play: (track: Track) => void
  pause: () => void
  togglePlay: () => void
  next: () => void
  prev: () => void
  setVolume: (v: number) => void
  setIsMuted: (m: boolean) => void
  setRepeatMode: (m: RepeatMode) => void
  setIsShuffled: (s: boolean) => void
  addToQueue: (track: Track) => void
  addTracksToQueue: (tracks: Track[]) => void
  removeFromQueue: (trackId: string) => void
  removeMultipleFromQueue: (trackIds: string[]) => void
  moveInQueue: (fromIndex: number, toIndex: number) => void
  playNow: (track: Track) => void
  playNext: (track: Track) => void
  clearQueue: () => void
  clearRecent: () => void
  toggleLike: (trackId: string) => void
  playAll: (tracks: Track[]) => void
  playFromQueue: (index: number) => void
}

interface PlayerProgress {
  progress: number
  duration: number
  setProgress: (p: number) => void
}

type PlayerContextValue = PlayerState & PlayerActions

interface BackendSnapshot {
  currentTrack: Track | null
  isPlaying: boolean
  progress: number
  duration: number
  volume: number
  isMuted: boolean
  repeatMode: RepeatMode
  isShuffled: boolean
  autoPlay: boolean
  queue: Track[]
  loadingAudio: boolean
  recentTracks?: Track[]
}

const PlayerContext = createContext<PlayerContextValue | null>(null)
const PlayerProgressContext = createContext<PlayerProgress | null>(null)

function shouldIgnoreSpaceShortcut(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false
  if (target.isContentEditable) return true
  const tagName = target.tagName.toLowerCase()
  if (['input', 'textarea', 'select', 'button'].includes(tagName)) return true
  const role = target.getAttribute('role')
  return Boolean(role && ['button', 'textbox', 'searchbox', 'slider', 'switch', 'combobox'].includes(role))
}

function syncLikedFlags(track: Track | null, favIds: Set<string>): Track | null {
  if (!track) return null
  const liked = favIds.has(track.id)
  return track.isLiked === liked ? track : { ...track, isLiked: liked }
}

function mergeRecentFromBackend(backendRecent: Track[] | undefined, favIds: Set<string>): void {
  if (!backendRecent?.length) return
  const existing = loadRecentTracks()
  const seen = new Set<string>()
  const merged: Track[] = []
  for (const t of [...backendRecent, ...existing]) {
    if (!t?.id || seen.has(t.id)) continue
    seen.add(t.id)
    merged.push({ ...t, isLiked: favIds.has(t.id) })
    if (merged.length >= 50) break
  }
  saveRecentTracks(merged)
}

export function isTrackInQueue(
  queue: readonly Track[],
  track: Pick<Track, 'id' | 'bvid' | 'page'>,
): boolean {
  return queue.some(
    t => t.id === track.id || (!track.page && Boolean(track.bvid) && t.bvid === track.bvid && Boolean(t.page)),
  )
}

export const REPEAT_MODE_ORDER: readonly RepeatMode[] = ['none', 'all', 'one']
export const REPEAT_MODE_LABELS: Record<RepeatMode, string> = {
  none: '不循环',
  all: '列表循环',
  one: '单曲循环',
}

export function PlayerProvider({ children }: { children: ReactNode }) {
  const { settings } = useAppSettings()
  const [currentTrack, setCurrentTrack] = useState<Track | null>(null)
  const [isPlaying, setIsPlaying] = useState(false)
  const [progress, setProgress] = useState(0)
  const [duration, setDuration] = useState(0)
  const [volume, setVolumeState] = useState(80)
  const [isMuted, setIsMutedState] = useState(false)
  const [repeatMode, setRepeatModeState] = useState<RepeatMode>('none')
  const [isShuffled, setIsShuffledState] = useState(false)
  const [queue, setQueue] = useState<Track[]>([])
  const [loadingAudio, setLoadingAudio] = useState(false)
  const [toast, setToast] = useState<string | null>(null)

  const wsRef = useRef<WebSocket | null>(null)
  const toastTimerRef = useRef<ReturnType<typeof setTimeout> | undefined>(undefined)
  const seekSuppressUntilRef = useRef(0)
  const queueRef = useRef<Track[]>([])
  const currentTrackRef = useRef<Track | null>(null)

  useEffect(() => {
    queueRef.current = queue
  }, [queue])

  useEffect(() => {
    currentTrackRef.current = currentTrack
  }, [currentTrack])

  const showToast = useCallback((msg: string) => {
    setToast(msg)
    if (toastTimerRef.current) clearTimeout(toastTimerRef.current)
    toastTimerRef.current = setTimeout(() => setToast(null), 2000)
  }, [])

  const applySnapshot = useCallback((snap: BackendSnapshot) => {
    const favIds = new Set(loadFavoriteTracks().map(t => t.id))
    const nextTrack = syncLikedFlags(snap.currentTrack || null, favIds)
    const nextQueue = Array.isArray(snap.queue)
      ? snap.queue.map(t => ({ ...t, isLiked: favIds.has(t.id) }))
      : []

    setCurrentTrack(nextTrack)
    setQueue(nextQueue)
    setIsPlaying(Boolean(snap.isPlaying))
    setDuration(Math.max(0, Number(snap.duration || 0)))
    if (Date.now() > seekSuppressUntilRef.current) {
      setProgress(Math.max(0, Number(snap.progress || 0)))
    }
    setVolumeState(Math.min(100, Math.max(0, Number(snap.volume ?? 80))))
    setIsMutedState(Boolean(snap.isMuted))
    setRepeatModeState(snap.repeatMode === 'one' || snap.repeatMode === 'all' ? snap.repeatMode : 'none')
    setIsShuffledState(Boolean(snap.isShuffled))
    setLoadingAudio(Boolean(snap.loadingAudio))
    mergeRecentFromBackend(snap.recentTracks, favIds)
  }, [])

  const sendAction = useCallback((payload: Record<string, unknown>) => {
    const ws = wsRef.current
    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify(payload))
      return
    }
    void fetch('/api/player/action', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    }).catch(() => {})
  }, [])

  // Initial state hydration + real-time WebSocket subscription
  useEffect(() => {
    let closed = false
    let reconnectTimer: ReturnType<typeof setTimeout> | undefined

    fetch('/api/player/state')
      .then(r => (r.ok ? r.json() : null))
      .then((snap: BackendSnapshot | null) => {
        if (!closed && snap) applySnapshot(snap)
      })
      .catch(() => {})

    const connectWs = () => {
      if (closed) return
      const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
      const ws = new WebSocket(`${proto}//${window.location.host}/ws`)
      wsRef.current = ws

      ws.onmessage = (event) => {
        if (closed) return
        try {
          const msg = JSON.parse(event.data) as { type: string; data: any }
          if (msg.type === 'state') {
            applySnapshot(msg.data as BackendSnapshot)
          } else if (msg.type === 'progress') {
            const p = msg.data as { progress?: number; duration?: number; isPlaying?: boolean }
            if (typeof p.duration === 'number') setDuration(Math.max(0, p.duration))
            if (typeof p.isPlaying === 'boolean') setIsPlaying(p.isPlaying)
            if (typeof p.progress === 'number' && Date.now() > seekSuppressUntilRef.current) {
              setProgress(Math.max(0, p.progress))
            }
          }
        } catch {
          // ignore malformed frames
        }
      }

      ws.onclose = () => {
        if (wsRef.current === ws) wsRef.current = null
        if (!closed) {
          reconnectTimer = setTimeout(connectWs, 1000)
        }
      }
    }

    connectWs()
    return () => {
      closed = true
      if (reconnectTimer) clearTimeout(reconnectTimer)
      wsRef.current?.close()
      wsRef.current = null
    }
  }, [applySnapshot])

  useEffect(() => {
    sendAction({ action: 'setAutoPlay', autoPlay: settings.autoPlay })
  }, [settings.autoPlay, sendAction])

  const play = useCallback((track: Track) => {
    sendAction({ action: 'play', track })
  }, [sendAction])

  const pause = useCallback(() => {
    sendAction({ action: 'pause' })
  }, [sendAction])

  const togglePlay = useCallback(() => {
    sendAction({ action: 'togglePlay' })
  }, [sendAction])

  const next = useCallback(() => {
    sendAction({ action: 'next' })
  }, [sendAction])

  const prev = useCallback(() => {
    sendAction({ action: 'prev' })
  }, [sendAction])

  const handleSetProgress = useCallback((p: number) => {
    const nextPos = Math.max(0, p)
    seekSuppressUntilRef.current = Date.now() + 350
    setProgress(nextPos)
    sendAction({ action: 'seek', progress: nextPos })
  }, [sendAction])

  const handleSetVolume = useCallback((v: number) => {
    setVolumeState(v)
    sendAction({ action: 'setVolume', volume: v })
  }, [sendAction])

  const setIsMuted = useCallback((m: boolean) => {
    setIsMutedState(m)
    sendAction({ action: 'setMuted', muted: m })
  }, [sendAction])

  const setRepeatMode = useCallback((mode: RepeatMode) => {
    setRepeatModeState(mode)
    sendAction({ action: 'setRepeatMode', mode })
  }, [sendAction])

  const setIsShuffled = useCallback((shuffled: boolean) => {
    setIsShuffledState(shuffled)
    sendAction({ action: 'setShuffled', shuffled })
  }, [sendAction])

  const addToQueue = useCallback((track: Track) => {
    const exists = isTrackInQueue(queueRef.current, track)
    sendAction({ action: 'addToQueue', track })
    showToast(exists ? '已在播放列表中' : '已加入播放列表')
  }, [sendAction, showToast])

  const addTracksToQueue = useCallback((tracks: Track[]) => {
    sendAction({ action: 'addTracksToQueue', tracks })
  }, [sendAction])

  const removeFromQueue = useCallback((trackId: string) => {
    sendAction({ action: 'removeFromQueue', trackId })
  }, [sendAction])

  const removeMultipleFromQueue = useCallback((trackIds: string[]) => {
    sendAction({ action: 'removeMultipleFromQueue', trackIds })
  }, [sendAction])

  const moveInQueue = useCallback((fromIndex: number, toIndex: number) => {
    sendAction({ action: 'moveInQueue', fromIndex, toIndex })
  }, [sendAction])

  const playNow = useCallback((track: Track) => {
    sendAction({ action: 'playNow', track })
  }, [sendAction])

  const playNext = useCallback((track: Track) => {
    sendAction({ action: 'playNext', track })
    if (currentTrackRef.current) {
      showToast('已设为下一首播放')
    }
  }, [sendAction, showToast])

  const clearQueue = useCallback(() => {
    sendAction({ action: 'clearQueue' })
  }, [sendAction])

  const clearRecent = useCallback(() => {
    saveRecentTracks([])
    sendAction({ action: 'clearRecent' })
  }, [sendAction])

  const toggleLike = useCallback((trackId: string) => {
    const track = queueRef.current.find(t => t.id === trackId) || currentTrackRef.current
    let nextLiked = false
    if (track) {
      const favs = toggleFavoriteTrack(track)
      nextLiked = favs.some(t => t.id === trackId)
    }
    setCurrentTrack(prev => (prev && prev.id === trackId ? { ...prev, isLiked: nextLiked } : prev))
    setQueue(prev => prev.map(t => (t.id === trackId ? { ...t, isLiked: nextLiked } : t)))
    sendAction({ action: 'updateLikeState', trackId, isLiked: nextLiked })
  }, [sendAction])

  const playAll = useCallback((tracks: Track[]) => {
    if (tracks.length === 0) return
    const favIds = new Set(loadFavoriteTracks().map(t => t.id))
    const synced = tracks.map(t => ({ ...t, isLiked: favIds.has(t.id) }))
    sendAction({ action: 'playAll', tracks: synced })
  }, [sendAction])

  const playFromQueue = useCallback((index: number) => {
    sendAction({ action: 'playFromQueue', index })
  }, [sendAction])

  useEffect(() => {
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.repeat || event.code !== 'Space' || shouldIgnoreSpaceShortcut(event.target)) return
      event.preventDefault()
      togglePlay()
    }
    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [togglePlay])

  const value = useMemo<PlayerContextValue>(() => ({
    currentTrack,
    isPlaying,
    volume,
    isMuted,
    repeatMode,
    isShuffled,
    queue,
    loadingAudio,
    play,
    pause,
    togglePlay,
    next,
    prev,
    setVolume: handleSetVolume,
    setIsMuted,
    setRepeatMode,
    setIsShuffled,
    addToQueue,
    addTracksToQueue,
    removeFromQueue,
    removeMultipleFromQueue,
    moveInQueue,
    playNow,
    playNext,
    clearQueue,
    clearRecent,
    toggleLike,
    playAll,
    playFromQueue,
  }), [
    currentTrack, isPlaying, volume, isMuted, repeatMode, isShuffled, queue, loadingAudio,
    play, pause, togglePlay, next, prev, handleSetVolume, setIsMuted, setRepeatMode, setIsShuffled,
    addToQueue, addTracksToQueue, removeFromQueue, removeMultipleFromQueue, moveInQueue,
    playNow, playNext, clearQueue, clearRecent, toggleLike, playAll, playFromQueue,
  ])

  const progressValue = useMemo<PlayerProgress>(() => ({
    progress,
    duration,
    setProgress: handleSetProgress,
  }), [progress, duration, handleSetProgress])

  return (
    <PlayerContext.Provider value={value}>
      <PlayerProgressContext.Provider value={progressValue}>
        {children}
        {toast && (
          <div
            style={{
              position: 'fixed',
              left: '50%',
              bottom: 96,
              transform: 'translateX(-50%)',
              zIndex: 80,
              padding: '8px 18px',
              borderRadius: 'var(--radius-full)',
              background: 'var(--glass-bg-heavy)',
              backdropFilter: 'blur(20px)',
              WebkitBackdropFilter: 'blur(20px)',
              border: '1px solid var(--glass-border)',
              boxShadow: 'var(--shadow-lg)',
              color: 'var(--color-foreground)',
              fontSize: 13,
              fontFamily: 'var(--font-body)',
              pointerEvents: 'none',
              whiteSpace: 'nowrap',
            } as React.CSSProperties}
          >
            {toast}
          </div>
        )}
      </PlayerProgressContext.Provider>
    </PlayerContext.Provider>
  )
}

export function usePlayer(): PlayerContextValue {
  const ctx = useContext(PlayerContext)
  if (!ctx) throw new Error('usePlayer must be used within PlayerProvider')
  return ctx
}

export function usePlayerProgress(): PlayerProgress {
  const ctx = useContext(PlayerProgressContext)
  if (!ctx) throw new Error('usePlayerProgress must be used within PlayerProvider')
  return ctx
}
