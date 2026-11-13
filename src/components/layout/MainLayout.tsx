import { useEffect, useState } from 'react'
import { Outlet } from 'react-router-dom'
import TitleBar from './TitleBar'
import Sidebar from './Sidebar'
import PlayerBar from './PlayerBar'
import NowPlaying from '@/components/NowPlaying'

const TRAY_SUSPEND_DELAY_MS = 15_000

export default function MainLayout() {
  const [traySuspended, setTraySuspended] = useState(false)

  useEffect(() => {
    const api = window.electronAPI
    if (!api?.onHiddenToTray || !api?.onShownFromTray) return
    let timer: ReturnType<typeof setTimeout> | null = null
    const clearPending = () => {
      if (timer) {
        clearTimeout(timer)
        timer = null
      }
    }
    const offHidden = api.onHiddenToTray(() => {
      clearPending()
      // 隐藏到托盘 15s 后卸载前台页面树（保留外层 PlayerProvider 播放与队列），释放列表 DOM/纹理内存
      timer = setTimeout(() => {
        timer = null
        setTraySuspended(true)
      }, TRAY_SUSPEND_DELAY_MS)
    })
    const offShown = api.onShownFromTray(() => {
      clearPending()
      setTraySuspended(false)
    })
    return () => {
      clearPending()
      offHidden?.()
      offShown?.()
    }
  }, [])

  if (traySuspended) return null

  return (
    <div
      style={{
        display: 'flex',
        flexDirection: 'column',
        height: '100vh',
        width: '100vw',
      }}
    >
      <TitleBar />

      <div
        style={{
          display: 'flex',
          flex: 1,
          overflow: 'hidden',
        }}
      >
        <Sidebar />

        <main
          style={{
            flex: 1,
            overflowY: 'auto',
            overflowX: 'hidden',
            background: 'var(--color-background)',
            padding: 'var(--space-lg) var(--space-xl)',
          }}
        >
          <Outlet />
        </main>
      </div>

      <PlayerBar />

      <NowPlaying />
    </div>
  )
}