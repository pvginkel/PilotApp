import { useState, useEffect, useCallback, useRef } from 'react'
import type { ReactNode } from 'react'
import { useQueryClient, type QueryClient } from '@tanstack/react-query'
import { isTestMode } from '@/lib/config/test-mode'
import { NEW_VERSION } from '@/lib/config/new-version'
import { emitTestEvent } from '@/lib/test/event-emitter'
import { useVersionSSE } from '../hooks/use-version-sse'
import { useSseContext } from './sse-context'
import { DeploymentContext } from './deployment-context-base'
import type { DeploymentContextValue } from './deployment-context-base'

type DeploymentBridge = {
  connect: (requestId?: string) => void
  disconnect: () => void
  getStatus: () => { isConnected: boolean; requestId: string | null }
  getRequestId: () => string | null
  getCurrentVersion: () => string | null
}

interface DeploymentProviderProps {
  children: ReactNode
}

/** How often a held reload looks at the page's fields again. */
const RELOAD_LOOK_MS = 1000

const TEXT_INPUTS = new Set(['text', 'search', 'email', 'url', 'tel', 'password', 'number'])

function isField(element: Element | null): element is HTMLElement {
  return (
    element instanceof HTMLTextAreaElement ||
    (element instanceof HTMLInputElement && TEXT_INPUTS.has(element.type)) ||
    (element instanceof HTMLElement && element.isContentEditable)
  )
}

/**
 * What a reload would take from what is being typed, or null where it takes nothing: a field's
 * words it would put out of sight, those of any field but one whose words stand in it again after
 * a reload (`data-survives-reload`); a write on its way, such as an answer sent from a field that
 * closed on Send; or, unless the tab has just come back into view, the keys of a field with the
 * focus.
 */
function reloadHold(queryClient: QueryClient, returning: boolean): 'words' | 'write' | 'focus' | null {
  for (const field of document.querySelectorAll('textarea, input, [contenteditable]')) {
    if (!isField(field) || field.hasAttribute('data-survives-reload')) continue
    const words = field instanceof HTMLTextAreaElement || field instanceof HTMLInputElement ? field.value : (field.textContent ?? '')
    if (words.trim() !== '') return 'words'
  }
  if (queryClient.isMutating() > 0) return 'write'
  return !returning && isField(document.activeElement) ? 'focus' : null
}

export function DeploymentProvider({ children }: DeploymentProviderProps) {
  const [isNewVersionAvailable, setIsNewVersionAvailable] = useState(false)
  const [isReloadOwed, setIsReloadOwed] = useState(false)
  const [currentVersion, setCurrentVersion] = useState<string | null>(null)

  const { isConnected, version } = useVersionSSE()
  const queryClient = useQueryClient()
  const sseContext = useSseContext()
  const { requestId } = sseContext

  const isConnectedRef = useRef(isConnected)
  const deploymentRequestIdRef = useRef<string | null>(requestId)
  const currentVersionRef = useRef<string | null>(currentVersion)
  const deploymentControlsRef = useRef<DeploymentBridge | null>(null)
  const sseContextRef = useRef(sseContext)

  useEffect(() => {
    isConnectedRef.current = isConnected
  }, [isConnected])

  useEffect(() => {
    deploymentRequestIdRef.current = requestId
  }, [requestId])

  useEffect(() => {
    sseContextRef.current = sseContext
  }, [sseContext])

  useEffect(() => {
    currentVersionRef.current = currentVersion
  }, [currentVersion])

  const checkForUpdates = useCallback(() => {
    // Trigger SSE reconnection (for window focus handler)
    sseContext.reconnect()
  }, [sseContext])

  const reloadApp = useCallback(() => {
    window.location.reload()
  }, [])

  // Handle version changes from SSE
  useEffect(() => {
    if (version) {
      if (currentVersion === null) {
        // First version received - set as current
        // eslint-disable-next-line react-hooks/set-state-in-effect -- Intentional state synchronization from SSE
        setCurrentVersion(version)
      } else if (version !== currentVersion) {
        // Version changed - new version available
        if (NEW_VERSION === 'banner') setIsNewVersionAvailable(true)
        else setIsReloadOwed(true)
      }
    }
  }, [version, currentVersion])

  // A reload owed waits for the first look that finds it takes nothing being typed in: at once,
  // every second after, and as the tab comes back into view. While it waits, a test event says why.
  useEffect(() => {
    if (!isReloadOwed) {
      return
    }
    let held: string | null = null
    let reloading = false
    const look = (returning: boolean) => {
      if (reloading) return
      const hold = reloadHold(queryClient, returning)
      if (hold === null) {
        reloading = true
        reloadApp()
      } else if (hold !== held) {
        held = hold
        emitTestEvent({ kind: 'ui_state', scope: 'deployment.reload', phase: 'loading', metadata: { held: hold } })
      }
    }
    const onVisible = () => {
      if (document.visibilityState === 'visible') look(true)
    }
    const timer = window.setInterval(() => look(false), RELOAD_LOOK_MS)
    document.addEventListener('visibilitychange', onVisible)
    look(false)
    return () => {
      window.clearInterval(timer)
      document.removeEventListener('visibilitychange', onVisible)
    }
  }, [isReloadOwed, queryClient, reloadApp])

  // Handle window focus to trigger reconnection (production mode or SharedWorker test mode)
  useEffect(() => {
    const hasSharedWorkerParam = typeof window !== 'undefined' &&
      new URLSearchParams(window.location.search).has('__sharedWorker')
    const shouldAutoConnect = (!isTestMode() && !import.meta.env.DEV) || hasSharedWorkerParam
    if (!shouldAutoConnect) {
      return
    }

    const handleFocus = () => {
      checkForUpdates()
    }

    window.addEventListener('focus', handleFocus)
    return () => window.removeEventListener('focus', handleFocus)
  }, [checkForUpdates])

  useEffect(() => {
    if (!isTestMode()) {
      return
    }

    if (typeof window === 'undefined') {
      return
    }

    const globalWindow = window as typeof window & {
      __deploymentSseControls?: DeploymentBridge | null
    }

    if (!deploymentControlsRef.current) {
      deploymentControlsRef.current = {
        connect: () => {
          // In test mode, manually trigger SSE connection
          // This allows tests to control connection timing and request ID
          sseContextRef.current.reconnect()
        },
        disconnect: () => {
          // No-op: disconnection is not exposed from SseContextProvider
          // Tests should rely on connection state rather than explicit disconnect
        },
        getStatus: () => ({
          isConnected: isConnectedRef.current,
          requestId: deploymentRequestIdRef.current
        }),
        getRequestId: () => {
          return deploymentRequestIdRef.current
        },
        // The version the banner compares against: the first one received.
        // A spec waits for it before sending a newer one.
        getCurrentVersion: () => {
          return currentVersionRef.current
        }
      }
      globalWindow.__deploymentSseControls = deploymentControlsRef.current
    } else {
      globalWindow.__deploymentSseControls = deploymentControlsRef.current
    }

    return () => {
      if (globalWindow.__deploymentSseControls === deploymentControlsRef.current) {
        delete globalWindow.__deploymentSseControls
      }
      deploymentControlsRef.current = null
    }
  }, [])

  const contextValue: DeploymentContextValue = {
    isNewVersionAvailable,
    currentVersion,
    deploymentRequestId: requestId,
    checkForUpdates,
    reloadApp
  }

  return (
    <DeploymentContext.Provider value={contextValue}>
      {children}
    </DeploymentContext.Provider>
  )
}
