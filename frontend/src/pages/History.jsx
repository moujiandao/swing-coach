import { useState, useEffect } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { getHistory } from '../lib/api'
import Spinner from '../components/Spinner'

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

function HistoryCard({ analysis, onClick }) {
  const { status, stroke_type, pro_reference, overall_score, created_at } = analysis
  const badgeClass = STATUS_BADGE[status] ?? STATUS_BADGE.pending

  return (
    <button
      type="button"
      onClick={onClick}
      className="w-full text-left rounded-2xl border border-gray-800 bg-gray-900 p-5 hover:border-gray-600 hover:bg-gray-800/60 transition-colors"
    >
      <div className="flex items-start justify-between gap-4">
        <div className="space-y-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <span className="text-sm font-medium text-white">{formatStroke(stroke_type)}</span>
            {pro_reference && (
              <span className="text-xs text-gray-500">vs {pro_reference.charAt(0).toUpperCase() + pro_reference.slice(1)}</span>
            )}
          </div>
          <p className="text-xs text-gray-500">{formatDate(created_at)}</p>
        </div>

        <div className="flex items-center gap-3 shrink-0">
          {overall_score != null && (
            <span className={`text-lg font-bold ${scoreColor(overall_score)}`}>
              {Math.round(overall_score)}
            </span>
          )}
          <span className={`rounded-full border px-2 py-0.5 text-xs font-medium capitalize ${badgeClass}`}>
            {status}
          </span>
        </div>
      </div>
    </button>
  )
}

export default function History() {
  const navigate = useNavigate()
  const [analyses, setAnalyses] = useState(null)
  const [isLoading, setIsLoading] = useState(true)
  const [error, setError] = useState(null)

  useEffect(() => {
    getHistory(50)
      .then((data) => setAnalyses(data))
      .catch((err) => setError(err?.response?.data?.detail || err.message || 'Failed to load history.'))
      .finally(() => setIsLoading(false))
  }, [])

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold text-white">Your Analyses</h1>
        <Link
          to="/"
          className="rounded-xl bg-[#2D8653] px-4 py-2 text-sm font-semibold text-white hover:bg-[#236b42] transition-colors"
        >
          + New Upload
        </Link>
      </div>

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
            />
          ))}
        </div>
      )}
    </div>
  )
}
