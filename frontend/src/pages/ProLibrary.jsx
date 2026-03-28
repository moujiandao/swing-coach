import { useState, useEffect, useCallback, useRef } from 'react'
import { Plus } from 'lucide-react'
import { getProReferences } from '../lib/api'
import ProReferenceCard from '../components/ProReferenceCard'
import AddProReferenceModal from '../components/AddProReferenceModal'

const STROKE_OPTIONS = [
  { value: '', label: 'All Strokes' },
  { value: 'forehand', label: 'Forehand' },
  { value: 'backhand_one', label: '1H Backhand' },
  { value: 'backhand_two', label: '2H Backhand' },
  { value: 'serve_flat', label: 'Flat Serve' },
  { value: 'serve_kick', label: 'Kick Serve' },
  { value: 'serve_slice', label: 'Slice Serve' },
  { value: 'volley', label: 'Volley' },
]

const STATUS_OPTIONS = [
  { value: '', label: 'All Statuses' },
  { value: 'ready', label: 'Ready' },
  { value: 'processing', label: 'Processing' },
  { value: 'pending', label: 'Pending' },
  { value: 'failed', label: 'Failed' },
]

// 6 skeleton cards for the loading state
function SkeletonCard() {
  return (
    <div className="rounded-xl border border-gray-800 bg-gray-900 overflow-hidden animate-pulse">
      <div className="aspect-video bg-gray-800" />
      <div className="px-4 pt-3 pb-4 space-y-2">
        <div className="h-4 w-2/3 rounded bg-gray-700" />
        <div className="flex gap-2">
          <div className="h-3 w-20 rounded-full bg-gray-700" />
          <div className="h-3 w-14 rounded-full bg-gray-700 ml-auto" />
        </div>
        <div className="h-3 w-24 rounded bg-gray-700" />
      </div>
    </div>
  )
}

function Toast({ message, onDismiss }) {
  useEffect(() => {
    const t = setTimeout(onDismiss, 4000)
    return () => clearTimeout(t)
  }, [onDismiss])

  return (
    <div className="fixed bottom-6 right-6 z-50 flex items-center gap-3 rounded-xl border border-[#2D8653]/40 bg-gray-900 px-4 py-3 shadow-2xl">
      <span className="h-2 w-2 rounded-full bg-[#2D8653]" />
      <p className="text-sm text-white">{message}</p>
    </div>
  )
}

export default function ProLibrary() {
  const [references, setReferences] = useState([])
  const [loading, setLoading] = useState(true)
  const [fetchError, setFetchError] = useState(null)
  const [strokeFilter, setStrokeFilter] = useState('')
  const [statusFilter, setStatusFilter] = useState('')
  const [showModal, setShowModal] = useState(false)
  const [toast, setToast] = useState(null)
  const pollRef = useRef(null)

  const fetchReferences = useCallback(async () => {
    const params = {}
    if (strokeFilter) params.stroke_type = strokeFilter
    if (statusFilter) params.status = statusFilter

    try {
      const data = await getProReferences(params)
      setReferences(data)
      setFetchError(null)
    } catch (err) {
      setFetchError(err?.response?.data?.detail || 'Failed to load pro references')
    } finally {
      setLoading(false)
    }
  }, [strokeFilter, statusFilter])

  // Initial fetch + re-fetch on filter change
  useEffect(() => {
    setLoading(true)
    fetchReferences()
  }, [fetchReferences])

  // Auto-poll every 5s while any card is still processing/pending
  useEffect(() => {
    const hasInFlight = references.some(
      (r) => r.status === 'processing' || r.status === 'pending',
    )

    if (hasInFlight && !pollRef.current) {
      pollRef.current = setInterval(() => {
        fetchReferences()
      }, 5000)
    }

    if (!hasInFlight && pollRef.current) {
      clearInterval(pollRef.current)
      pollRef.current = null
    }

    return () => {
      if (pollRef.current) {
        clearInterval(pollRef.current)
        pollRef.current = null
      }
    }
  }, [references, fetchReferences])

  function handleDelete(deletedId) {
    setReferences((prev) => prev.filter((r) => r.id !== deletedId))
  }

  function handleModalSuccess() {
    setToast('Processing started — the card will update when ready.')
    fetchReferences()
  }

  const selectClass =
    'rounded-lg border border-gray-700 bg-gray-900 px-3 py-2 text-sm text-gray-100 focus:border-[#2D8653] focus:outline-none'

  return (
    <div>
      {/* Header */}
      <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold text-white">Pro Reference Library</h1>
          <p className="mt-1 text-sm text-gray-400">Upload pro player swings to compare against</p>
        </div>
        <button
          onClick={() => setShowModal(true)}
          className="flex items-center gap-2 rounded-xl bg-[#2D8653] px-4 py-2.5 text-sm font-semibold text-white hover:bg-[#236b42] transition-colors shrink-0"
        >
          <Plus className="h-4 w-4" />
          Add Pro Reference
        </button>
      </div>

      {/* Filter bar */}
      <div className="flex flex-wrap gap-3 mb-6">
        <select
          value={strokeFilter}
          onChange={(e) => setStrokeFilter(e.target.value)}
          className={selectClass}
        >
          {STROKE_OPTIONS.map(({ value, label }) => (
            <option key={value} value={value}>{label}</option>
          ))}
        </select>
        <select
          value={statusFilter}
          onChange={(e) => setStatusFilter(e.target.value)}
          className={selectClass}
        >
          {STATUS_OPTIONS.map(({ value, label }) => (
            <option key={value} value={value}>{label}</option>
          ))}
        </select>
      </div>

      {/* Content */}
      {fetchError ? (
        <div className="rounded-lg border border-red-800 bg-red-900/30 px-4 py-4 text-sm text-red-300">
          {fetchError}
        </div>
      ) : loading ? (
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {Array.from({ length: 6 }).map((_, i) => (
            <SkeletonCard key={i} />
          ))}
        </div>
      ) : references.length === 0 ? (
        <div className="flex flex-col items-center justify-center rounded-xl border border-dashed border-gray-700 py-20 text-center">
          <svg viewBox="0 0 80 80" className="h-16 w-16 text-gray-700 mb-4" fill="currentColor">
            <circle cx="40" cy="22" r="10" />
            <path d="M20 70c0-11 9-20 20-20s20 9 20 20" />
          </svg>
          <p className="text-gray-400 font-medium">No pro references yet</p>
          <p className="text-sm text-gray-600 mt-1 mb-4">Upload your first pro reference to get started</p>
          <button
            onClick={() => setShowModal(true)}
            className="flex items-center gap-2 rounded-xl bg-[#2D8653] px-4 py-2 text-sm font-semibold text-white hover:bg-[#236b42] transition-colors"
          >
            <Plus className="h-4 w-4" />
            Add Pro Reference
          </button>
        </div>
      ) : (
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {references.map((ref) => (
            <ProReferenceCard
              key={ref.id}
              reference={ref}
              onUpdate={fetchReferences}
              onDelete={handleDelete}
            />
          ))}
        </div>
      )}

      {/* Modal */}
      {showModal && (
        <AddProReferenceModal
          onClose={() => setShowModal(false)}
          onSuccess={handleModalSuccess}
        />
      )}

      {/* Toast */}
      {toast && (
        <Toast message={toast} onDismiss={() => setToast(null)} />
      )}
    </div>
  )
}
