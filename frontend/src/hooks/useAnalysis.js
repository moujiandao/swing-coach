import { useState, useEffect, useRef } from 'react'
import { getAnalysis } from '../lib/api'

const POLL_INTERVAL_MS = 2000
const TERMINAL_STATUSES = new Set(['completed', 'failed'])

export function useAnalysis(analysisId) {
  const [analysis, setAnalysis] = useState(null)
  const [isLoading, setIsLoading] = useState(true)
  const [error, setError] = useState(null)
  const timerRef = useRef(null)

  useEffect(() => {
    if (!analysisId) return

    let cancelled = false

    async function fetchOnce() {
      try {
        const data = await getAnalysis(analysisId)
        if (cancelled) return
        setAnalysis(data)
        setIsLoading(false)

        if (!TERMINAL_STATUSES.has(data.status)) {
          timerRef.current = setTimeout(fetchOnce, POLL_INTERVAL_MS)
        }
      } catch (err) {
        if (cancelled) return
        setError(err?.response?.data?.detail || err.message || 'Failed to load analysis.')
        setIsLoading(false)
      }
    }

    fetchOnce()

    return () => {
      cancelled = true
      clearTimeout(timerRef.current)
    }
  }, [analysisId])

  const isProcessing = analysis?.status === 'pending' || analysis?.status === 'processing'

  return { analysis, isLoading, error, isProcessing }
}
