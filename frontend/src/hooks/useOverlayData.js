import { useState, useEffect, useCallback } from 'react'
import { getOverlay } from '../lib/api'

/**
 * Fetches overlay data for canvas rendering.
 * Only triggers when analysisStatus is 'completed'.
 * Returns a refetch function so callers can retry on error.
 */
export function useOverlayData(analysisId, analysisStatus) {
  const [overlayData, setOverlayData] = useState(null)
  const [isLoading, setIsLoading] = useState(false)
  const [error, setError] = useState(null)
  const [retryKey, setRetryKey] = useState(0)

  useEffect(() => {
    if (!analysisId || analysisStatus !== 'completed') return

    let cancelled = false
    setIsLoading(true)
    setError(null)

    getOverlay(analysisId)
      .then((data) => {
        if (!cancelled) setOverlayData(data)
      })
      .catch((err) => {
        if (!cancelled) {
          setError(err?.response?.data?.detail || err.message || 'Failed to load overlay data')
        }
      })
      .finally(() => {
        if (!cancelled) setIsLoading(false)
      })

    return () => { cancelled = true }
  }, [analysisId, analysisStatus, retryKey])

  const refetch = useCallback(() => setRetryKey((k) => k + 1), [])

  return { overlayData, isLoading, error, refetch }
}
