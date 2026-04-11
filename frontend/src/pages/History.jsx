import { useState, useEffect } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { Trash2, RotateCcw } from 'lucide-react'
import { getHistory, cancelAnalysis, deleteAnalysis, bulkDeleteAnalyses, reprocessAnalysis } from '../lib/api'

const STATUS_BADGE = {
  completed:  'bg-green-900/40 text-green-400 border-green-800',
  failed:     'bg-red-900/40 text-red-400 border-red-800',
  processing: 'bg-yellow-900/40 text-yellow-400 border-yellow-800',
  pending:    'bg-gray-800 text-gray-400 border-gray-700',
}

function scoreColor(score) {
  if (score == null) return 'text-gray-500'
  if (score >= 80) return 'text-[#2D8653]'
  if (score >= 60) return 'text-yellow-400'
  if (score >= 40) return 'text-orange-400'
  return 'text-red-400'
}

function formatStroke(stroke) {
  return stroke?.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase()) ?? '—'
}

function formatDate(iso) {
  if (!iso) return '—'
  return new Date(iso).toLocaleString(undefined, {
    month: 'short', day: 'numeric', year: 'numeric',
    hour: 'numeric', minute: '2-digit',
  })
}

function SkeletonCard() {
  return (
    <div className="rounded-2xl border border-gray-800 bg-gray-900 p-5 animate-pulse">
      <div className="flex items-start justify-between gap-4">
        <div className="space-y-2 flex-1">
          <div className="h-4 w-32 rounded bg-gray-800" />
          <div className="h-3 w-48 rounded bg-gray-800" />
        </div>
        <div className="h-6 w-16 rounded-full bg-gray-800" />
      </div>
    </div>
  )
}

function HistoryCard({ analysis, onClick, onCancel, onDelete, onReprocess, isSelected, onToggleSelect }) {
  const { status, stroke_type, pro_reference, overall_score, created_at } = analysis
  const badgeClass = STATUS_BADGE[status] ?? STATUS_BADGE.pending
  const cancellable = status === 'processing' || status === 'pending'
  const reprocessable = status === 'completed' || status === 'failed'
  const [confirmingDelete, setConfirmingDelete] = useState(false)

  return (
    <div className={`relative w-full text-left rounded-2xl border bg-gray-900 p-5 transition-colors
      ${isSelected ? 'border-[#2D8653] bg-[#2D8653]/5' : 'border-gray-800 hover:border-gray-600 hover:bg-gray-800/60'}
    `}>
      <div className="flex items-start gap-3">
        {/* Checkbox */}
        <label className="flex items-center pt-1 shrink-0 cursor-pointer">
          <input
            type="checkbox"
            checked={isSelected}
            onChange={() => onToggleSelect(analysis.id)}
            className="accent-[#2D8653] h-4 w-4"
          />
        </label>

        {/* Main content (clickable) */}
        <button type="button" onClick={onClick} className="space-y-1 min-w-0 flex-1 text-left">
          <div className="flex items-center gap-2 flex-wrap">
            <span className="text-sm font-medium text-white">{formatStroke(stroke_type)}</span>
            {pro_reference && (
              <span className="text-xs text-gray-500">vs {pro_reference.charAt(0).toUpperCase() + pro_reference.slice(1)}</span>
            )}
          </div>
          <p className="text-xs text-gray-500">{formatDate(created_at)}</p>
        </button>

        <div className="flex items-center gap-3 shrink-0">
          {overall_score != null && (
            <span className={`text-lg font-bold ${scoreColor(overall_score)}`}>
              {Math.round(overall_score)}
            </span>
          )}
          <span className={`rounded-full border px-2 py-0.5 text-xs font-medium capitalize ${badgeClass}`}>
            {status}
          </span>
          {cancellable && (
            <button
              type="button"
              onClick={(e) => { e.stopPropagation(); onCancel(analysis.id) }}
              className="rounded-lg border border-red-800 bg-red-900/30 px-2 py-0.5 text-xs font-medium text-red-400 hover:bg-red-900/60 transition-colors"
            >
              Cancel
            </button>
          )}
          {/* Reprocess button */}
          {reprocessable && (
            <button
              type="button"
              onClick={(e) => { e.stopPropagation(); onReprocess(analysis.id) }}
              className="p-1.5 rounded-lg text-gray-500 hover:text-[#2D8653] hover:bg-[#2D8653]/10 transition-colors cursor-pointer"
              aria-label="Reprocess analysis"
              title="Reprocess"
            >
              <RotateCcw className="h-4 w-4" />
            </button>
          )}
          {/* Individual delete button */}
          <button
            type="button"
            onClick={(e) => { e.stopPropagation(); setConfirmingDelete(true) }}
            className="p-1.5 rounded-lg text-gray-500 hover:text-red-400 hover:bg-red-900/20 transition-colors"
            aria-label="Delete analysis"
          >
            <Trash2 className="h-4 w-4" />
          </button>
        </div>
      </div>

      {/* Inline delete confirmation */}
      {confirmingDelete && (
        <div className="absolute inset-0 z-10 flex items-center justify-center gap-4 rounded-2xl bg-gray-900/95 px-6">
          <p className="text-sm text-gray-300">Delete this analysis?</p>
          <button
            onClick={() => setConfirmingDelete(false)}
            className="rounded-lg border border-gray-600 px-3 py-1 text-sm text-gray-300 hover:border-gray-400 hover:text-white transition-colors"
          >
            Cancel
          </button>
          <button
            onClick={() => { setConfirmingDelete(false); onDelete(analysis.id) }}
            className="rounded-lg bg-red-700 px-3 py-1 text-sm font-semibold text-white hover:bg-red-600 transition-colors"
          >
            Delete
          </button>
        </div>
      )}
    </div>
  )
}

export default function History() {
  const navigate = useNavigate()
  const [analyses, setAnalyses] = useState(null)
  const [isLoading, setIsLoading] = useState(true)
  const [error, setError] = useState(null)
  const [selectedIds, setSelectedIds] = useState(new Set())
  const [confirmBulk, setConfirmBulk] = useState(false)
  const [deleting, setDeleting] = useState(false)

  useEffect(() => {
    getHistory(50)
      .then((data) => setAnalyses(data))
      .catch((err) => setError(err?.response?.data?.detail || err.message || 'Failed to load history.'))
      .finally(() => setIsLoading(false))
  }, [])

  const handleCancel = async (analysisId) => {
    try {
      await cancelAnalysis(analysisId)
      setAnalyses((prev) =>
        prev.map((a) =>
          a.id === analysisId ? { ...a, status: 'failed', error_message: 'Cancelled by user' } : a
        )
      )
    } catch (err) {
      setError(err?.response?.data?.detail || 'Failed to cancel analysis')
    }
  }

  const handleReprocess = async (analysisId) => {
    try {
      await reprocessAnalysis(analysisId)
      setAnalyses((prev) =>
        prev.map((a) =>
          a.id === analysisId ? { ...a, status: 'processing', error_message: null } : a
        )
      )
    } catch (err) {
      setError(err?.response?.data?.detail || 'Failed to reprocess analysis')
    }
  }

  const handleDelete = async (analysisId) => {
    try {
      await deleteAnalysis(analysisId)
      setAnalyses((prev) => prev.filter((a) => a.id !== analysisId))
      setSelectedIds((prev) => {
        const next = new Set(prev)
        next.delete(analysisId)
        return next
      })
    } catch (err) {
      setError(err?.response?.data?.detail || 'Failed to delete analysis')
    }
  }

  const handleBulkDelete = async () => {
    if (selectedIds.size === 0) return
    setDeleting(true)
    try {
      await bulkDeleteAnalyses([...selectedIds])
      setAnalyses((prev) => prev.filter((a) => !selectedIds.has(a.id)))
      setSelectedIds(new Set())
      setConfirmBulk(false)
    } catch (err) {
      setError(err?.response?.data?.detail || 'Failed to delete analyses')
    } finally {
      setDeleting(false)
    }
  }

  const toggleSelect = (id) => {
    setSelectedIds((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  const toggleSelectAll = () => {
    if (!analyses) return
    if (selectedIds.size === analyses.length) {
      setSelectedIds(new Set())
    } else {
      setSelectedIds(new Set(analyses.map((a) => a.id)))
    }
  }

  const allSelected = analyses?.length > 0 && selectedIds.size === analyses.length

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between flex-wrap gap-3">
        <h1 className="text-2xl font-bold text-white">Your Analyses</h1>
        <Link
          to="/"
          className="rounded-xl bg-[#2D8653] px-4 py-2 text-sm font-semibold text-white hover:bg-[#236b42] transition-colors"
        >
          + New Upload
        </Link>
      </div>

      {/* Bulk actions bar */}
      {analyses?.length > 0 && (
        <div className="flex items-center gap-4 text-sm">
          <label className="flex items-center gap-2 cursor-pointer select-none text-gray-400 hover:text-white transition-colors">
            <input
              type="checkbox"
              checked={allSelected}
              onChange={toggleSelectAll}
              className="accent-[#2D8653] h-4 w-4"
            />
            {allSelected ? 'Deselect All' : 'Select All'}
          </label>

          {selectedIds.size > 0 && (
            <button
              type="button"
              onClick={() => setConfirmBulk(true)}
              className="flex items-center gap-1.5 rounded-lg border border-red-800 bg-red-900/30 px-3 py-1.5 text-xs font-medium text-red-400 hover:bg-red-900/60 transition-colors"
            >
              <Trash2 className="h-3.5 w-3.5" />
              Delete Selected ({selectedIds.size})
            </button>
          )}
        </div>
      )}

      {/* Bulk delete confirmation dialog */}
      {confirmBulk && (
        <div className="rounded-xl border border-red-800 bg-red-900/20 px-5 py-4 flex items-center justify-between gap-4">
          <p className="text-sm text-red-300">
            Delete {selectedIds.size} {selectedIds.size === 1 ? 'analysis' : 'analyses'}? This cannot be undone.
          </p>
          <div className="flex gap-3 shrink-0">
            <button
              onClick={() => setConfirmBulk(false)}
              disabled={deleting}
              className="rounded-lg border border-gray-600 px-4 py-1.5 text-sm text-gray-300 hover:border-gray-400 hover:text-white transition-colors disabled:opacity-50"
            >
              Cancel
            </button>
            <button
              onClick={handleBulkDelete}
              disabled={deleting}
              className="rounded-lg bg-red-700 px-4 py-1.5 text-sm font-semibold text-white hover:bg-red-600 disabled:opacity-50 transition-colors"
            >
              {deleting ? 'Deleting...' : 'Confirm Delete'}
            </button>
          </div>
        </div>
      )}

      {isLoading && (
        <div className="space-y-3">
          {[0, 1, 2].map((i) => <SkeletonCard key={i} />)}
        </div>
      )}

      {error && (
        <div className="rounded-xl border border-red-800 bg-red-900/30 px-4 py-3 text-sm text-red-300">
          {error}
        </div>
      )}

      {!isLoading && !error && analyses?.length === 0 && (
        <div className="flex flex-col items-center justify-center py-24 text-center space-y-4">
          <p className="text-gray-400">No analyses yet.</p>
          <Link
            to="/"
            className="inline-block rounded-xl bg-[#2D8653] px-6 py-2.5 text-sm font-semibold text-white hover:bg-[#236b42] transition-colors"
          >
            Upload Your First Swing
          </Link>
        </div>
      )}

      {!isLoading && !error && analyses?.length > 0 && (
        <div className="space-y-3">
          {analyses.map((a) => (
            <HistoryCard
              key={a.id}
              analysis={a}
              onClick={() => navigate(`/analysis/${a.id}`)}
              onCancel={handleCancel}
              onDelete={handleDelete}
              onReprocess={handleReprocess}
              isSelected={selectedIds.has(a.id)}
              onToggleSelect={toggleSelect}
            />
          ))}
        </div>
      )}
    </div>
  )
}
