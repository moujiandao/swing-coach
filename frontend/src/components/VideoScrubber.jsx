import { useRef, useCallback, useEffect } from 'react'

// ---------------------------------------------------------------------------
// Phase color palette (also used by PhaseTimeline)
// ---------------------------------------------------------------------------
export const PHASE_COLORS = {
  preparation:    '#4b5563', // gray-600
  backswing:      '#1d4ed8', // blue-700
  forward_swing:  '#15803d', // green-700
  contact:        '#ca8a04', // yellow-600
  follow_through: '#7c3aed', // purple-700
}

export const PHASE_ORDER = [
  ['preparation',    'Preparation'],
  ['backswing',      'Backswing'],
  ['forward_swing',  'Forward Swing'],
  ['contact',        'Contact'],
  ['follow_through', 'Follow-through'],
]

// ---------------------------------------------------------------------------
// Helper: build CSS linear-gradient from phase boundaries
// ---------------------------------------------------------------------------
function buildPhaseGradient(phaseBoundaries, totalFrames) {
  if (!phaseBoundaries || totalFrames <= 0) return '#374151'

  const stops = []
  for (const [key] of PHASE_ORDER) {
    const b = phaseBoundaries[key]
    const color = PHASE_COLORS[key]
    if (!b || !color) continue
    const start = ((b.user_start / totalFrames) * 100).toFixed(2)
    const end = ((Math.min(b.user_end + 1, totalFrames) / totalFrames) * 100).toFixed(2)
    stops.push(`${color} ${start}%`, `${color} ${end}%`)
  }

  return stops.length ? `linear-gradient(to right, ${stops.join(', ')})` : '#374151'
}

// ---------------------------------------------------------------------------
// Helper: format frame as time string
// ---------------------------------------------------------------------------
function formatTime(frame, fps) {
  const secs = frame / Math.max(fps, 1)
  return `${secs.toFixed(1)}s`
}

// ---------------------------------------------------------------------------
// VideoScrubber
// ---------------------------------------------------------------------------

/**
 * VideoScrubber
 *
 * Full playback controls for the overlay canvas:
 *   - Play / pause button
 *   - Step forward / backward (1 frame each)
 *   - Speed selector (0.25x / 0.5x / 1x)
 *   - Phase-colored draggable scrubber bar
 *   - Phase quick-jump buttons
 */
export default function VideoScrubber({
  totalFrames = 1,
  currentFrame = 0,
  onFrameChange,
  fps = 30,
  isPlaying = false,
  onPlayPause,
  onStepForward,
  onStepBackward,
  phaseBoundaries = null,
  playbackSpeed = 1,
  onSpeedChange,
  onSeekToPhase,
}) {
  const trackRef = useRef(null)
  const isDragging = useRef(false)

  // --- Scrubber drag ---

  const frameFromPointer = useCallback(
    (clientX) => {
      const track = trackRef.current
      if (!track) return currentFrame
      const { left, width } = track.getBoundingClientRect()
      const ratio = Math.max(0, Math.min((clientX - left) / width, 1))
      return Math.round(ratio * (totalFrames - 1))
    },
    [currentFrame, totalFrames],
  )

  const handleTrackMouseDown = useCallback(
    (e) => {
      isDragging.current = true
      onFrameChange?.(frameFromPointer(e.clientX))
    },
    [frameFromPointer, onFrameChange],
  )

  useEffect(() => {
    const handleMove = (e) => {
      if (!isDragging.current) return
      onFrameChange?.(frameFromPointer(e.clientX))
    }
    const handleUp = () => {
      isDragging.current = false
    }
    document.addEventListener('mousemove', handleMove)
    document.addEventListener('mouseup', handleUp)
    return () => {
      document.removeEventListener('mousemove', handleMove)
      document.removeEventListener('mouseup', handleUp)
    }
  }, [frameFromPointer, onFrameChange])

  // --- Derived values ---
  const progressPct = totalFrames > 1 ? (currentFrame / (totalFrames - 1)) * 100 : 0
  const phaseGradient = buildPhaseGradient(phaseBoundaries, totalFrames)

  // Which phase is currently active (for jump-button highlight)
  let activePhase = null
  if (phaseBoundaries) {
    for (const [key] of PHASE_ORDER) {
      const b = phaseBoundaries[key]
      if (b && currentFrame >= b.user_start && currentFrame <= b.user_end) {
        activePhase = key
        break
      }
    }
  }

  // Phase label positions (only show if the phase segment is wide enough)
  const phaseLabels = phaseBoundaries
    ? PHASE_ORDER.map(([key, label]) => {
        const b = phaseBoundaries[key]
        if (!b) return null
        const startPct = (b.user_start / totalFrames) * 100
        const widthPct = ((b.user_end - b.user_start + 1) / totalFrames) * 100
        if (widthPct < 8) return null // too narrow to label
        return { key, label, startPct, midPct: startPct + widthPct / 2 }
      }).filter(Boolean)
    : []

  const speeds = [0.25, 0.5, 1.0]

  return (
    <div className="space-y-3 select-none">
      {/* ---- Scrubber bar ---- */}
      <div className="space-y-1">
        {/* Phase labels above the bar */}
        {phaseLabels.length > 0 && (
          <div className="relative h-4 text-[10px] text-white/60 font-medium">
            {phaseLabels.map(({ key, label, midPct }) => (
              <span
                key={key}
                className="absolute -translate-x-1/2 truncate"
                style={{ left: `${midPct}%` }}
              >
                {label}
              </span>
            ))}
          </div>
        )}

        {/* Track */}
        <div
          ref={trackRef}
          className="relative h-3 rounded-full cursor-pointer overflow-visible"
          style={{ background: phaseGradient }}
          onMouseDown={handleTrackMouseDown}
          role="slider"
          aria-valuemin={0}
          aria-valuemax={totalFrames - 1}
          aria-valuenow={currentFrame}
          tabIndex={0}
          onKeyDown={(e) => {
            if (e.key === 'ArrowRight') onStepForward?.()
            if (e.key === 'ArrowLeft') onStepBackward?.()
          }}
        >
          {/* Thumb */}
          <div
            className="absolute top-1/2 -translate-y-1/2 -translate-x-1/2 w-4 h-4 rounded-full bg-white shadow-md ring-2 ring-white/40 pointer-events-none"
            style={{ left: `${progressPct}%` }}
          />
        </div>

        {/* Time readout */}
        <div className="flex justify-between text-xs text-gray-400 font-mono">
          <span>
            Frame {currentFrame} / {totalFrames - 1}
          </span>
          <span>
            {formatTime(currentFrame, fps)} / {formatTime(totalFrames - 1, fps)}
          </span>
        </div>
      </div>

      {/* ---- Transport controls ---- */}
      <div className="flex items-center justify-between gap-3">
        {/* Step + play/pause */}
        <div className="flex items-center gap-1">
          <button
            onClick={onStepBackward}
            className="w-8 h-8 rounded-lg bg-gray-800 hover:bg-gray-700 text-gray-200 text-sm flex items-center justify-center transition-colors"
            title="Step back 1 frame"
            aria-label="Step back"
          >
            &#9664;&#9664;
          </button>

          <button
            onClick={onPlayPause}
            className="w-10 h-10 rounded-xl bg-[#2D8653] hover:bg-[#236b42] text-white font-bold flex items-center justify-center transition-colors text-base"
            title={isPlaying ? 'Pause' : 'Play'}
            aria-label={isPlaying ? 'Pause' : 'Play'}
          >
            {isPlaying ? (
              // Pause icon (two vertical bars)
              <span className="flex gap-0.5">
                <span className="block w-[3px] h-4 bg-white rounded" />
                <span className="block w-[3px] h-4 bg-white rounded" />
              </span>
            ) : (
              // Play triangle
              <span style={{ marginLeft: '2px' }}>&#9654;</span>
            )}
          </button>

          <button
            onClick={onStepForward}
            className="w-8 h-8 rounded-lg bg-gray-800 hover:bg-gray-700 text-gray-200 text-sm flex items-center justify-center transition-colors"
            title="Step forward 1 frame"
            aria-label="Step forward"
          >
            &#9654;&#9654;
          </button>
        </div>

        {/* Speed selector */}
        <div className="flex items-center gap-1">
          <span className="text-xs text-gray-500 mr-1">Speed</span>
          {speeds.map((s) => (
            <button
              key={s}
              onClick={() => onSpeedChange?.(s)}
              className={`px-2 py-1 rounded text-xs font-medium transition-colors ${
                playbackSpeed === s
                  ? 'bg-[#2D8653] text-white'
                  : 'bg-gray-800 text-gray-400 hover:text-white hover:bg-gray-700'
              }`}
            >
              {s === 1 ? '1x' : `${s}x`}
            </button>
          ))}
        </div>
      </div>

      {/* ---- Phase quick-jump buttons ---- */}
      {phaseBoundaries && (
        <div className="flex flex-wrap gap-1.5">
          {PHASE_ORDER.map(([key, label]) => {
            if (!phaseBoundaries[key]) return null
            const isActive = activePhase === key
            return (
              <button
                key={key}
                onClick={() => onSeekToPhase?.(key)}
                className="px-2.5 py-1 rounded-lg text-xs font-medium transition-colors"
                style={{
                  background: isActive
                    ? PHASE_COLORS[key]
                    : `${PHASE_COLORS[key]}33`, // 20% opacity when inactive
                  color: isActive ? '#ffffff' : '#d1d5db',
                  border: `1px solid ${PHASE_COLORS[key]}66`,
                }}
              >
                {label}
              </button>
            )
          })}
        </div>
      )}
    </div>
  )
}
