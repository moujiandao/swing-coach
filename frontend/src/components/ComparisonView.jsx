import { useState, useRef, useEffect } from 'react'
import DualSkeletonCanvas from './DualSkeletonCanvas'
import SkeletonLegend from './SkeletonLegend'
import VideoScrubber, { PHASE_ORDER } from './VideoScrubber'
import PhaseTimeline from './PhaseTimeline'
import DeviationTimeline from './DeviationTimeline'
import FrameDeviationPanel from './FrameDeviationPanel'
import KeyboardShortcutsHelp from './KeyboardShortcutsHelp'
import { useVideoPlayback } from '../hooks/useVideoPlayback'
import { getStanceWidthDeviation } from '../lib/landmarks'

const ASPECT_RATIO = 9 / 16

// Speed steps for [ and ] shortcuts
const SPEED_STEPS = [0.25, 0.5, 1.0]

/**
 * ComparisonView
 *
 * The main interactive canvas container for analysis results.
 *
 * Display modes:
 *   - Overlay: user video with both skeletons drawn on top
 *   - Side-by-side: two canvases synced by phase progress (pre-aligned in API)
 *
 * Keyboard shortcuts: Space, arrows, 1-5, S, P, D, M, [, ], ?
 * Lazy-loads into view: the intersection observer defers render until scrolled into view.
 */
export default function ComparisonView({ overlayData }) {
  const {
    user_landmarks,
    pro_landmarks,
    frame_deviations,
    phase_boundaries,
    fps,
    landmark_connections,
    detection_mask,
    video_url,
  } = overlayData

  const totalFrames = user_landmarks?.length ?? 1

  const [mode, setMode] = useState('overlay') // 'overlay' | 'side-by-side'
  const [showUser, setShowUser] = useState(true)
  const [showPro, setShowPro] = useState(true)
  const [showDeviations, setShowDeviations] = useState(true)
  const [panelOpen, setPanelOpen] = useState(true)
  const [showHelp, setShowHelp] = useState(false)
  const [alignSkeletons, setAlignSkeletons] = useState(true)

  // Canvas sizing via ResizeObserver
  const containerRef = useRef(null)
  const [containerWidth, setContainerWidth] = useState(640)

  useEffect(() => {
    const el = containerRef.current
    if (!el) return
    setContainerWidth(Math.floor(el.getBoundingClientRect().width) || 640)
    const obs = new ResizeObserver(([entry]) => {
      const w = Math.floor(entry.contentRect.width)
      if (w > 0) setContainerWidth(w)
    })
    obs.observe(el)
    return () => obs.disconnect()
  }, [])

  // On narrow screens, force overlay (two canvases don't fit on mobile)
  const effectiveMode = mode === 'side-by-side' && containerWidth < 560 ? 'overlay' : mode

  // Canvas dimensions
  const overlayWidth  = containerWidth
  const overlayHeight = Math.round(overlayWidth * ASPECT_RATIO)
  const sideWidth     = Math.max(120, Math.floor((containerWidth - 12) / 2))
  const sideHeight    = Math.round(sideWidth * ASPECT_RATIO)

  const playback = useVideoPlayback({ totalFrames, fps: fps || 30, phaseBoundaries: phase_boundaries })
  const {
    currentFrame,
    isPlaying,
    playbackSpeed,
    setPlaybackSpeed,
    togglePlayPause,
    seekToFrame,
    seekToPhase,
    stepForward,
    stepBackward,
  } = playback

  // ---- Keyboard shortcuts ----
  useEffect(() => {
    const handleKey = (e) => {
      // Skip when user is focused on a form element
      const tag = e.target?.tagName
      if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') return

      switch (e.key) {
        case ' ':
          e.preventDefault()
          togglePlayPause()
          break
        case 'ArrowLeft':
          e.preventDefault()
          stepBackward()
          break
        case 'ArrowRight':
          e.preventDefault()
          stepForward()
          break
        case '?':
          setShowHelp((v) => !v)
          break
        case 's':
        case 'S':
          setShowUser((v) => !v)
          break
        case 'p':
        case 'P':
          setShowPro((v) => !v)
          break
        case 'd':
        case 'D':
          setShowDeviations((v) => !v)
          break
        case 'a':
        case 'A':
          setAlignSkeletons((v) => !v)
          break
        case 'm':
        case 'M':
          setMode((m) => (m === 'overlay' ? 'side-by-side' : 'overlay'))
          break
        case '[': {
          const idx = SPEED_STEPS.indexOf(playbackSpeed)
          if (idx > 0) setPlaybackSpeed(SPEED_STEPS[idx - 1])
          break
        }
        case ']': {
          const idx = SPEED_STEPS.indexOf(playbackSpeed)
          if (idx < SPEED_STEPS.length - 1) setPlaybackSpeed(SPEED_STEPS[idx + 1])
          break
        }
        default: {
          // 1–5: jump to phase by index
          const num = parseInt(e.key, 10)
          if (num >= 1 && num <= 5) {
            const phaseKey = PHASE_ORDER[num - 1]?.[0]
            if (phaseKey) seekToPhase(phaseKey)
          }
        }
      }
    }

    document.addEventListener('keydown', handleKey)
    return () => document.removeEventListener('keydown', handleKey)
  }, [togglePlayPause, stepBackward, stepForward, seekToPhase, playbackSpeed, setPlaybackSpeed])

  return (
    <>
      {showHelp && <KeyboardShortcutsHelp onClose={() => setShowHelp(false)} />}

      <div className="space-y-4">
        {/* ---- Controls row ---- */}
        <div className="flex items-center justify-between flex-wrap gap-2">
          {/* Mode toggle */}
          <div className="flex rounded-lg overflow-hidden border border-gray-700 text-xs font-medium">
            {[['overlay', 'Overlay'], ['side-by-side', 'Side by Side']].map(([m, label]) => (
              <button
                key={m}
                onClick={() => setMode(m)}
                className={`px-3 py-1.5 transition-colors ${
                  mode === m
                    ? 'bg-[#2D8653] text-white'
                    : 'bg-gray-900 text-gray-400 hover:text-white hover:bg-gray-800'
                }`}
              >
                {label}
              </button>
            ))}
          </div>

          {/* Skeleton / deviation toggles */}
          <div className="flex items-center gap-3 text-xs flex-wrap">
            <label className="flex items-center gap-1.5 cursor-pointer select-none">
              <input
                type="checkbox"
                checked={showUser}
                onChange={(e) => setShowUser(e.target.checked)}
                className="accent-[#00D4FF]"
              />
              <span className="text-[#00D4FF]">My Skeleton</span>
            </label>
            <label className="flex items-center gap-1.5 cursor-pointer select-none">
              <input
                type="checkbox"
                checked={showPro}
                onChange={(e) => setShowPro(e.target.checked)}
                className="accent-[#FFD700]"
              />
              <span className="text-[#FFD700]">Pro Skeleton</span>
            </label>
            <label className="flex items-center gap-1.5 cursor-pointer select-none">
              <input
                type="checkbox"
                checked={showDeviations}
                onChange={(e) => setShowDeviations(e.target.checked)}
                className="accent-[#EF4444]"
              />
              <span className="text-[#EF4444]">Deviations</span>
            </label>
            <label className="flex items-center gap-1.5 cursor-pointer select-none">
              <input
                type="checkbox"
                checked={alignSkeletons}
                onChange={(e) => setAlignSkeletons(e.target.checked)}
                className="accent-[#22C55E]"
              />
              <span className="text-[#22C55E]">Align</span>
            </label>

            {/* Help button */}
            <button
              onClick={() => setShowHelp(true)}
              className="w-6 h-6 rounded-full bg-gray-800 hover:bg-gray-700 text-gray-400 hover:text-white
                         text-xs font-bold transition-colors flex items-center justify-center"
              title="Keyboard shortcuts (?)"
              aria-label="Show keyboard shortcuts"
            >
              ?
            </button>
          </div>
        </div>

        {/* ---- Canvas area (container measured here for ResizeObserver) ---- */}
        <div ref={containerRef} className="w-full">
          {(() => {
            const stanceWidthDev = getStanceWidthDeviation(frame_deviations, currentFrame)
            return stanceWidthDev != null ? (
              <div className="text-xs text-gray-400 mb-1 font-mono">
                Stance:{' '}
                <span className={stanceWidthDev > 0 ? 'text-amber-400' : 'text-green-400'}>
                  {stanceWidthDev > 0 ? '+' : ''}{stanceWidthDev.toFixed(3)} vs pro
                </span>
              </div>
            ) : null
          })()}
          {effectiveMode === 'overlay' ? (
            <DualSkeletonCanvas
              videoSrc={video_url || null}
              userLandmarks={user_landmarks}
              proLandmarks={pro_landmarks}
              frameDeviations={frame_deviations}
              landmarkConnections={landmark_connections}
              phaseBoundaries={phase_boundaries}
              fps={fps || 30}
              currentFrame={currentFrame}
              showUserSkeleton={showUser}
              showProSkeleton={showPro}
              showDeviations={showDeviations}
              alignSkeletons={alignSkeletons}
              detectionMask={detection_mask}
              width={overlayWidth}
              height={overlayHeight}
            />
          ) : (
            <div className="flex gap-3">
              {/* Left: user video + user skeleton */}
              <div className="flex-1 min-w-0">
                <p className="text-xs text-[#00D4FF] font-medium mb-1">You</p>
                <DualSkeletonCanvas
                  videoSrc={video_url || null}
                  userLandmarks={user_landmarks}
                  proLandmarks={null}
                  frameDeviations={frame_deviations}
                  landmarkConnections={landmark_connections}
                  phaseBoundaries={phase_boundaries}
                  fps={fps || 30}
                  currentFrame={currentFrame}
                  showUserSkeleton={true}
                  showProSkeleton={false}
                  showDeviations={showDeviations}
                  alignSkeletons={alignSkeletons}
                  detectionMask={detection_mask}
                  width={sideWidth}
                  height={sideHeight}
                />
              </div>

              {/* Right: pro skeleton on dark background */}
              <div className="flex-1 min-w-0">
                <p className="text-xs text-[#FFD700] font-medium mb-1">Pro</p>
                <DualSkeletonCanvas
                  videoSrc={null}
                  userLandmarks={null}
                  proLandmarks={pro_landmarks}
                  frameDeviations={[]}
                  landmarkConnections={landmark_connections}
                  phaseBoundaries={phase_boundaries}
                  fps={fps || 30}
                  currentFrame={currentFrame}
                  showUserSkeleton={false}
                  showProSkeleton={true}
                  showDeviations={false}
                  alignSkeletons={alignSkeletons}
                  width={sideWidth}
                  height={sideHeight}
                />
              </div>
            </div>
          )}
        </div>

        {/* Legend */}
        <SkeletonLegend />

        {/* ---- Video scrubber ---- */}
        <div className="rounded-xl border border-gray-800 bg-gray-900 p-4">
          <VideoScrubber
            totalFrames={totalFrames}
            currentFrame={currentFrame}
            onFrameChange={seekToFrame}
            fps={fps || 30}
            isPlaying={isPlaying}
            onPlayPause={togglePlayPause}
            onStepForward={stepForward}
            onStepBackward={stepBackward}
            phaseBoundaries={phase_boundaries}
            playbackSpeed={playbackSpeed}
            onSpeedChange={setPlaybackSpeed}
            onSeekToPhase={seekToPhase}
          />
        </div>

        {/* ---- Phase timeline ---- */}
        {phase_boundaries && (
          <div className="rounded-xl border border-gray-800 bg-gray-900 p-4">
            <PhaseTimeline
              totalFrames={totalFrames}
              currentFrame={currentFrame}
              phaseBoundaries={phase_boundaries}
              onSeekToPhase={seekToPhase}
            />
          </div>
        )}

        {/* ---- Deviation timeline ---- */}
        {frame_deviations?.length > 0 && (
          <div className="rounded-xl border border-gray-800 bg-gray-900 p-4">
            <DeviationTimeline
              totalFrames={totalFrames}
              frameDeviations={frame_deviations}
              currentFrame={currentFrame}
              onSeekToFrame={seekToFrame}
            />
          </div>
        )}

        {/* ---- Frame deviation panel ---- */}
        <FrameDeviationPanel
          frameDeviations={frame_deviations}
          currentFrame={currentFrame}
          isOpen={panelOpen}
          onToggle={() => setPanelOpen((p) => !p)}
        />
      </div>
    </>
  )
}
