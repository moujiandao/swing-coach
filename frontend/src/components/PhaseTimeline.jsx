import { useRef, useCallback, useEffect } from 'react'
import { PHASE_COLORS, PHASE_ORDER } from './VideoScrubber'

// ---------------------------------------------------------------------------
// Tempo badge
// ---------------------------------------------------------------------------
function TempoBadge({ tempoRatio }) {
  if (tempoRatio == null) return null

  let label, bg, fg
  if (tempoRatio > 1.1) {
    label = `${tempoRatio.toFixed(1)}x slower`
    bg = '#78350f'
    fg = '#fbbf24'
  } else if (tempoRatio < 0.9) {
    label = `${tempoRatio.toFixed(1)}x faster`
    bg = '#14532d'
    fg = '#4ade80'
  } else {
    label = 'on pace'
    bg = '#1e3a5f'
    fg = '#93c5fd'
  }

  return (
    <span
      className="text-[9px] font-semibold px-1 py-0.5 rounded whitespace-nowrap"
      style={{ background: bg, color: fg }}
    >
      {label}
    </span>
  )
}

// ---------------------------------------------------------------------------
// PhaseTimeline
// ---------------------------------------------------------------------------

/**
 * PhaseTimeline
 *
 * A proportional-width timeline bar divided into phase segments.
 * - Each segment width is proportional to the user's frame count in that phase
 * - Shows phase name and tempo comparison vs pro inside each segment
 * - A vertical cursor line moves with currentFrame
 * - Clicking any segment seeks to the start of that phase
 */
export default function PhaseTimeline({
  totalFrames = 1,
  currentFrame = 0,
  phaseBoundaries = null,
  onSeekToPhase,
}) {
  const containerRef = useRef(null)

  if (!phaseBoundaries || totalFrames <= 0) return null

  const phases = PHASE_ORDER.map(([key, label]) => {
    const b = phaseBoundaries[key]
    if (!b) return null
    const userDuration = (b.user_end - b.user_start + 1)
    const widthPct = (userDuration / totalFrames) * 100
    return {
      key,
      label,
      widthPct,
      userDuration,
      proDuration: b.pro_duration_frames ?? null,
      tempoRatio: b.tempo_ratio ?? null,
      userStart: b.user_start,
    }
  }).filter(Boolean)

  if (!phases.length) return null

  const cursorPct = (currentFrame / (totalFrames - 1)) * 100

  return (
    <div className="space-y-1">
      <p className="text-xs font-semibold uppercase tracking-widest text-gray-500">
        Phase Timeline
      </p>

      {/* Timeline bar */}
      <div
        ref={containerRef}
        className="relative flex rounded-lg overflow-hidden h-16 cursor-pointer"
        style={{ background: '#1f2937' }}
      >
        {phases.map(({ key, label, widthPct, userDuration, tempoRatio, userStart }) => (
          <div
            key={key}
            className="relative flex flex-col items-start justify-center px-2 py-1 gap-0.5 overflow-hidden group transition-opacity hover:opacity-90"
            style={{
              width: `${widthPct}%`,
              background: PHASE_COLORS[key],
              minWidth: 0,
            }}
            onClick={() => onSeekToPhase?.(key)}
            title={`Jump to ${label} (frame ${userStart})`}
          >
            {/* Phase name */}
            <span className="text-white text-[10px] font-semibold leading-tight truncate w-full">
              {label}
            </span>

            {/* Frame count */}
            <span className="text-white/60 text-[9px] leading-tight">
              {userDuration}f
            </span>

            {/* Tempo badge */}
            <TempoBadge tempoRatio={tempoRatio} />
          </div>
        ))}

        {/* Current-position cursor */}
        <div
          className="absolute top-0 bottom-0 w-0.5 bg-white/80 pointer-events-none"
          style={{ left: `${cursorPct}%` }}
        />
      </div>

      {/* Phase color legend (compact) */}
      <div className="flex flex-wrap gap-x-3 gap-y-0.5">
        {phases.map(({ key, label }) => (
          <span key={key} className="flex items-center gap-1 text-[10px] text-gray-400">
            <span
              className="inline-block w-2 h-2 rounded-sm"
              style={{ background: PHASE_COLORS[key] }}
            />
            {label}
          </span>
        ))}
      </div>
    </div>
  )
}
