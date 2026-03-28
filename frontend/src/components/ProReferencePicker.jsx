import { useState, useEffect, useRef } from 'react'
import { Check, ChevronLeft, ChevronRight, Plus } from 'lucide-react'
import { getProReferences } from '../lib/api'
import AddProReferenceModal from './AddProReferenceModal'

/**
 * Horizontal scrollable row of pro reference mini-cards.
 * Auto-filters to the currently selected strokeType.
 * Calls onSelect(referenceId) when a card is picked.
 */
export default function ProReferencePicker({ strokeType, selectedId, onSelect }) {
  const [references, setReferences] = useState([])
  const [loading, setLoading] = useState(false)
  const [showModal, setShowModal] = useState(false)
  const scrollRef = useRef(null)

  useEffect(() => {
    if (!strokeType) {
      setReferences([])
      return
    }
    setLoading(true)
    getProReferences({ stroke_type: strokeType })
      .then(setReferences)
      .catch(() => setReferences([]))
      .finally(() => setLoading(false))
  }, [strokeType])

  function handleModalSuccess() {
    // Refresh the list after a new reference finishes processing
    if (strokeType) {
      getProReferences({ stroke_type: strokeType })
        .then(setReferences)
        .catch(() => {})
    }
  }

  function scroll(direction) {
    const el = scrollRef.current
    if (!el) return
    el.scrollBy({ left: direction * 160, behavior: 'smooth' })
  }

  if (!strokeType) return null

  if (!loading && references.length === 0) {
    return (
      <div className="rounded-lg border border-dashed border-gray-700 px-4 py-3 text-sm text-gray-400 flex items-center gap-3">
        <span>No pro references for this stroke.</span>
        <button
          type="button"
          onClick={() => setShowModal(true)}
          className="text-[#2D8653] hover:underline font-medium"
        >
          Add one in the Library
        </button>
        {showModal && (
          <AddProReferenceModal
            onClose={() => setShowModal(false)}
            onSuccess={handleModalSuccess}
          />
        )}
      </div>
    )
  }

  return (
    <div className="relative">
      {/* Left arrow */}
      <button
        type="button"
        onClick={() => scroll(-1)}
        className="absolute left-0 top-1/2 -translate-y-1/2 z-10 flex h-7 w-7 items-center justify-center rounded-full bg-gray-800 text-gray-400 hover:bg-gray-700 hover:text-white shadow"
        aria-label="Scroll left"
      >
        <ChevronLeft className="h-4 w-4" />
      </button>

      {/* Scrollable row */}
      <div
        ref={scrollRef}
        className="flex gap-3 overflow-x-auto scroll-smooth px-9 py-1 scrollbar-hide"
        style={{ scrollbarWidth: 'none' }}
      >
        {loading
          ? Array.from({ length: 3 }).map((_, i) => (
              <div
                key={i}
                className="flex-shrink-0 w-[120px] h-[100px] rounded-xl border border-gray-800 bg-gray-900 animate-pulse"
              />
            ))
          : references.map((ref) => {
              const isSelected = ref.id === selectedId
              const isReady = ref.status === 'ready'
              // Thumbnails are in S3; no direct URL in local dev — show placeholder
              const thumbnailUrl = null

              return (
                <button
                  key={ref.id}
                  type="button"
                  disabled={!isReady}
                  onClick={() => isReady && onSelect(ref.id)}
                  className={`relative flex-shrink-0 w-[120px] rounded-xl border overflow-hidden transition-all
                    ${isSelected
                      ? 'border-[#2D8653] ring-2 ring-[#2D8653]/40'
                      : isReady
                        ? 'border-gray-700 hover:border-gray-500'
                        : 'border-gray-800 opacity-50 cursor-not-allowed'
                    }`}
                >
                  {/* Thumbnail */}
                  <div className="h-[70px] bg-gray-800 overflow-hidden">
                    {thumbnailUrl ? (
                      <img
                        src={thumbnailUrl}
                        alt={ref.player_name}
                        className="w-full h-full object-cover"
                      />
                    ) : (
                      <div className="w-full h-full flex items-center justify-center text-gray-600 text-xs">
                        {isReady ? 'No preview' : 'Processing…'}
                      </div>
                    )}
                  </div>

                  {/* Name */}
                  <div className="px-2 py-1.5 text-center">
                    <p className="text-xs text-gray-300 truncate leading-tight">
                      {ref.player_name}
                    </p>
                  </div>

                  {/* Selected checkmark overlay */}
                  {isSelected && (
                    <div className="absolute top-1.5 right-1.5 flex h-5 w-5 items-center justify-center rounded-full bg-[#2D8653]">
                      <Check className="h-3 w-3 text-white" />
                    </div>
                  )}
                </button>
              )
            })}

        {/* Add New card */}
        <button
          type="button"
          onClick={() => setShowModal(true)}
          className="flex-shrink-0 w-[120px] h-[100px] rounded-xl border border-dashed border-gray-700 flex flex-col items-center justify-center gap-1.5 text-gray-500 hover:border-gray-500 hover:text-gray-300 transition-colors"
        >
          <Plus className="h-5 w-5" />
          <span className="text-xs">Add New</span>
        </button>
      </div>

      {/* Right arrow */}
      <button
        type="button"
        onClick={() => scroll(1)}
        className="absolute right-0 top-1/2 -translate-y-1/2 z-10 flex h-7 w-7 items-center justify-center rounded-full bg-gray-800 text-gray-400 hover:bg-gray-700 hover:text-white shadow"
        aria-label="Scroll right"
      >
        <ChevronRight className="h-4 w-4" />
      </button>

      {showModal && (
        <AddProReferenceModal
          onClose={() => setShowModal(false)}
          onSuccess={handleModalSuccess}
        />
      )}
    </div>
  )
}
