import { useState } from 'react'
import { Loader2, CheckCircle2, XCircle, ShieldCheck, MoreVertical, RefreshCw, Trash2 } from 'lucide-react'
import { reprocessProReference, deleteProReference } from '../lib/api'

const STROKE_LABELS = {
  forehand: 'Forehand',
  backhand_one: '1H Backhand',
  backhand_two: '2H Backhand',
  serve_flat: 'Flat Serve',
  serve_kick: 'Kick Serve',
  serve_slice: 'Slice Serve',
  volley: 'Volley',
}

function StatusBadge({ status }) {
  if (status === 'ready') {
    return (
      <span className="flex items-center gap-1 text-xs font-medium text-emerald-400">
        <CheckCircle2 className="h-3.5 w-3.5" /> Ready
      </span>
    )
  }
  if (status === 'processing' || status === 'pending') {
    return (
      <span className="flex items-center gap-1 text-xs font-medium text-amber-400">
        <Loader2 className="h-3.5 w-3.5 animate-spin" /> Processing...
      </span>
    )
  }
  if (status === 'failed') {
    return (
      <span className="flex items-center gap-1 text-xs font-medium text-red-400">
        <XCircle className="h-3.5 w-3.5" /> Failed
      </span>
    )
  }
  return null
}

function StatusDot({ status }) {
  if (status === 'ready') return <span className="absolute top-2 right-2 h-2.5 w-2.5 rounded-full bg-emerald-400 ring-2 ring-gray-900" />
  if (status === 'processing' || status === 'pending') return <span className="absolute top-2 right-2 h-2.5 w-2.5 rounded-full bg-amber-400 ring-2 ring-gray-900 animate-pulse" />
  if (status === 'failed') return <span className="absolute top-2 right-2 h-2.5 w-2.5 rounded-full bg-red-400 ring-2 ring-gray-900" />
  return null
}

export default function ProReferenceCard({ reference, onUpdate, onDelete }) {
  const [menuOpen, setMenuOpen] = useState(false)
  const [confirmDelete, setConfirmDelete] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)

  async function handleReprocess() {
    setMenuOpen(false)
    setBusy(true)
    setError(null)
    try {
      await reprocessProReference(reference.id)
      onUpdate?.()
    } catch (err) {
      setError(err?.response?.data?.detail || 'Reprocess failed')
    } finally {
      setBusy(false)
    }
  }

  async function handleDelete() {
    setBusy(true)
    setError(null)
    try {
      await deleteProReference(reference.id)
      onDelete?.(reference.id)
    } catch (err) {
      setError(err?.response?.data?.detail || 'Delete failed')
      setBusy(false)
      setConfirmDelete(false)
    }
  }

  const formattedDate = new Date(reference.created_at).toLocaleDateString('en-US', {
    month: 'short',
    day: 'numeric',
    year: 'numeric',
  })

  return (
    <div className="group relative rounded-xl border border-gray-800 bg-gray-900 overflow-hidden shadow-md hover:shadow-xl hover:scale-[1.02] transition-all duration-200">
      {/* Thumbnail */}
      <div className="relative aspect-video bg-gray-800 flex items-center justify-center">
        {reference.thumbnail_s3_key ? (
          <img
            src={reference.thumbnail_url}
            alt={`${reference.player_name} ${STROKE_LABELS[reference.stroke_type] ?? reference.stroke_type}`}
            className="w-full h-full object-cover"
          />
        ) : (
          /* Silhouette placeholder */
          <svg viewBox="0 0 80 80" className="h-16 w-16 text-gray-600" fill="currentColor">
            <circle cx="40" cy="22" r="10" />
            <path d="M20 70c0-11 9-20 20-20s20 9 20 20" />
            <line x1="40" y1="42" x2="28" y2="56" stroke="currentColor" strokeWidth="4" strokeLinecap="round" />
            <line x1="40" y1="42" x2="52" y2="56" stroke="currentColor" strokeWidth="4" strokeLinecap="round" />
            <line x1="40" y1="52" x2="40" y2="68" stroke="currentColor" strokeWidth="4" strokeLinecap="round" />
          </svg>
        )}
        <StatusDot status={reference.status} />
        {reference.is_builtin && (
          <span className="absolute top-2 left-2 flex items-center gap-1 rounded-full bg-gray-900/80 px-2 py-0.5 text-[10px] font-semibold text-[#2D8653]">
            <ShieldCheck className="h-3 w-3" /> Built-in
          </span>
        )}
      </div>

      {/* Body */}
      <div className="px-4 pt-3 pb-4 space-y-2">
        <div className="flex items-start justify-between gap-2">
          <h3 className="text-base font-semibold text-white leading-tight">{reference.player_name}</h3>
          {/* Context menu — hidden for builtin */}
          {!reference.is_builtin && (
            <div className="relative shrink-0">
              <button
                onClick={(e) => { e.stopPropagation(); setMenuOpen(v => !v) }}
                className="p-1 rounded hover:bg-gray-700 text-gray-400 hover:text-white transition-colors"
                disabled={busy}
              >
                <MoreVertical className="h-4 w-4" />
              </button>
              {menuOpen && (
                <div
                  className="absolute right-0 top-7 z-20 w-36 rounded-lg border border-gray-700 bg-gray-800 shadow-xl py-1"
                  onMouseLeave={() => setMenuOpen(false)}
                >
                  <button
                    onClick={handleReprocess}
                    className="flex w-full items-center gap-2 px-3 py-2 text-sm text-gray-300 hover:bg-gray-700 hover:text-white"
                  >
                    <RefreshCw className="h-3.5 w-3.5" /> Reprocess
                  </button>
                  <button
                    onClick={(e) => { e.stopPropagation(); setMenuOpen(false); setConfirmDelete(true) }}
                    className="flex w-full items-center gap-2 px-3 py-2 text-sm text-red-400 hover:bg-gray-700 hover:text-red-300"
                  >
                    <Trash2 className="h-3.5 w-3.5" /> Delete
                  </button>
                </div>
              )}
            </div>
          )}
        </div>

        <div className="flex items-center justify-between gap-2">
          <span className="rounded-full bg-[#2D8653]/20 border border-[#2D8653]/30 px-2 py-0.5 text-[11px] font-medium text-[#2D8653]">
            {STROKE_LABELS[reference.stroke_type] ?? reference.stroke_type}
          </span>
          <StatusBadge status={reference.status} />
        </div>

        {reference.status === 'failed' && reference.error_message && (
          <p className="text-[11px] text-red-400 leading-snug">{reference.error_message}</p>
        )}

        {error && (
          <p className="text-[11px] text-red-400">{error}</p>
        )}

        <p className="text-xs text-gray-500 pt-0.5">{formattedDate}</p>
      </div>

      {/* Delete confirmation overlay */}
      {confirmDelete && (
        <div className="absolute inset-0 z-30 flex flex-col items-center justify-center gap-4 rounded-xl bg-gray-900/95 px-5 text-center">
          <p className="text-sm font-medium text-white">Delete <span className="text-[#2D8653]">{reference.player_name}</span>?</p>
          <p className="text-xs text-gray-400">This removes the video and pose data permanently.</p>
          <div className="flex gap-3">
            <button
              onClick={() => setConfirmDelete(false)}
              className="rounded-lg border border-gray-600 px-4 py-1.5 text-sm text-gray-300 hover:border-gray-400 hover:text-white transition-colors"
            >
              Cancel
            </button>
            <button
              onClick={handleDelete}
              disabled={busy}
              className="rounded-lg bg-red-700 px-4 py-1.5 text-sm font-semibold text-white hover:bg-red-600 disabled:opacity-50 transition-colors"
            >
              {busy ? 'Deleting…' : 'Delete'}
            </button>
          </div>
        </div>
      )}
    </div>
  )
}
