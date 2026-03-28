import { useEffect } from 'react'
import { useParams, Link } from 'react-router-dom'
import { useAnalysis } from '../hooks/useAnalysis'
import { useOverlayData } from '../hooks/useOverlayData'
import ProcessingState from '../components/ProcessingState'
import ScoreGauge from '../components/ScoreGauge'
import PhaseBreakdown from '../components/PhaseBreakdown'
import DeviationCard from '../components/DeviationCard'
import CoachingFeedback from '../components/CoachingFeedback'
import ComparisonView from '../components/ComparisonView'

function formatStroke(stroke) {
  return stroke?.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase()) ?? stroke
}

function capitalize(s) {
  return s ? s.charAt(0).toUpperCase() + s.slice(1) : s
}

function Breadcrumbs({ id }) {
  return (
    <nav className="text-xs text-gray-600 flex items-center gap-1.5" aria-label="Breadcrumb">
      <Link to="/" className="hover:text-gray-400 transition-colors">Home</Link>
      <span>/</span>
      <Link to="/history" className="hover:text-gray-400 transition-colors">History</Link>
      <span>/</span>
      <span className="text-gray-500">Analysis #{id?.slice(0, 8)}</span>
    </nav>
  )
}

// Skeleton placeholder shown while overlay data loads
function CanvasSkeleton() {
  return (
    <div className="w-full aspect-video rounded-xl bg-gray-900 border border-gray-800 flex items-center justify-center animate-pulse">
      <p className="text-xs text-gray-600">Loading comparison view...</p>
    </div>
  )
}

// Shown when overlay data fails to load
function OverlayError({ message, onRetry }) {
  return (
    <div className="w-full rounded-xl border border-gray-800 bg-gray-900 p-6 text-center space-y-3">
      <p className="text-sm text-gray-400">
        Couldn&apos;t load comparison data. Try refreshing.
      </p>
      {message && <p className="text-xs text-gray-600">{message}</p>}
      <button
        onClick={onRetry}
        className="inline-block rounded-lg bg-gray-800 hover:bg-gray-700 px-4 py-2 text-xs text-gray-200 transition-colors"
      >
        Retry
      </button>
    </div>
  )
}

export default function Analysis() {
  const { id } = useParams()
  const { analysis, isLoading, error, isProcessing } = useAnalysis(id)
  const {
    overlayData,
    isLoading: overlayLoading,
    error: overlayError,
    refetch: overlayRefetch,
  } = useOverlayData(id, analysis?.status)

  // Page title
  useEffect(() => {
    document.title = 'SwingCoach - Analysis Results'
    return () => { document.title = 'SwingCoach' }
  }, [])

  // Initial load
  if (isLoading) return <ProcessingState />

  // Network / fetch error
  if (error) {
    return (
      <div className="mx-auto max-w-lg py-16 text-center space-y-4">
        <p className="text-red-400">{error}</p>
        <Link
          to="/"
          className="inline-block rounded-xl bg-[#2D8653] px-6 py-2.5 text-sm font-semibold text-white hover:bg-[#236b42] transition-colors"
        >
          Try Again
        </Link>
      </div>
    )
  }

  // Still processing
  if (isProcessing) return <ProcessingState />

  // Failed status
  if (analysis?.status === 'failed') {
    return (
      <div className="mx-auto max-w-lg py-16 text-center space-y-4">
        <h2 className="text-xl font-semibold text-white">Analysis Failed</h2>
        <p className="text-gray-400 text-sm">
          {analysis.error_message || 'Something went wrong processing your video.'}
        </p>
        <Link
          to="/"
          className="inline-block rounded-xl bg-[#2D8653] px-6 py-2.5 text-sm font-semibold text-white hover:bg-[#236b42] transition-colors"
        >
          Try Again
        </Link>
      </div>
    )
  }

  // Completed
  const { overall_score, phase_scores, deviations, coaching_feedback, stroke_type, pro_reference } = analysis

  return (
    <div className="space-y-8">
      {/* Breadcrumbs */}
      <Breadcrumbs id={id} />

      {/* ---- Header ---- */}
      <div className="flex items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold text-white">Swing Analysis</h1>
          {stroke_type && (
            <p className="text-sm text-gray-400 mt-1">
              {formatStroke(stroke_type)}
              {pro_reference && (
                <>
                  {' '}&mdash; compared against{' '}
                  <span className="text-gray-200">{capitalize(pro_reference)}</span>
                </>
              )}
            </p>
          )}
        </div>
        <Link
          to="/"
          className="shrink-0 text-xs text-gray-500 hover:text-gray-300 transition-colors mt-1"
        >
          - New Upload
        </Link>
      </div>

      {/* ---- TOP: Score + phase breakdown ---- */}
      <div className="grid gap-6 sm:grid-cols-2">
        <div className="rounded-2xl border border-gray-800 bg-gray-900 p-6 flex flex-col items-center justify-center gap-2">
          <h2 className="text-xs font-semibold uppercase tracking-widest text-gray-500 mb-2">
            Overall Score
          </h2>
          <ScoreGauge score={overall_score ?? 0} />
        </div>
        <div className="rounded-2xl border border-gray-800 bg-gray-900 p-6">
          <h2 className="text-xs font-semibold uppercase tracking-widest text-gray-500 mb-4">
            Phase Breakdown
          </h2>
          <PhaseBreakdown phaseScores={phase_scores} />
        </div>
      </div>

      {/* ---- MIDDLE: Comparison view ---- */}
      <div>
        <h2 className="text-xs font-semibold uppercase tracking-widest text-gray-500 mb-4">
          Frame-by-Frame Comparison
        </h2>
        {overlayLoading && <CanvasSkeleton />}
        {!overlayLoading && overlayError && (
          <OverlayError message={overlayError} onRetry={overlayRefetch} />
        )}
        {!overlayLoading && !overlayError && overlayData && (
          <ComparisonView overlayData={overlayData} />
        )}
        {!overlayLoading && !overlayError && !overlayData && (
          <div className="rounded-xl border border-gray-800 bg-gray-900 p-4 text-center text-xs text-gray-500">
            Comparison overlay not available for this analysis. Re-analyze to see frame-by-frame
            comparison.
          </div>
        )}
      </div>

      {/* ---- BOTTOM: Deviations ---- */}
      {deviations?.length > 0 && (
        <div className="space-y-3">
          <h2 className="text-sm font-semibold uppercase tracking-widest text-gray-500">
            Deviations ({deviations.length})
          </h2>
          {deviations.map((dev, i) => (
            <DeviationCard key={i} deviation={dev} />
          ))}
        </div>
      )}

      {/* Coaching feedback */}
      {coaching_feedback && (
        <div className="space-y-3">
          <h2 className="text-sm font-semibold uppercase tracking-widest text-gray-500">
            Coaching Feedback
          </h2>
          <CoachingFeedback feedback={coaching_feedback} />
        </div>
      )}
    </div>
  )
}
