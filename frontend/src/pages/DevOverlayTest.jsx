/**
 * Dev-only overlay test page.
 *
 * Route: /dev/overlay-test
 * Only included in the router when import.meta.env.DEV is true.
 *
 * Renders DualSkeletonCanvas + VideoScrubber + PhaseTimeline with synthetic
 * data so you can verify rendering, playback, phase jumps, and tempo display
 * without a real analysis record.
 */
import { useState, useMemo } from 'react'
import DualSkeletonCanvas from '../components/DualSkeletonCanvas'
import SkeletonLegend from '../components/SkeletonLegend'
import VideoScrubber from '../components/VideoScrubber'
import PhaseTimeline from '../components/PhaseTimeline'
import { useVideoPlayback } from '../hooks/useVideoPlayback'

// BlazePose connections (same as backend LANDMARK_CONNECTIONS)
const LANDMARK_CONNECTIONS = [
  [11, 12], [11, 13], [13, 15], [12, 14], [14, 16],
  [11, 23], [12, 24], [23, 24],
  [23, 25], [25, 27], [24, 26], [26, 28],
]

const NUM_FRAMES = 60
const NUM_LANDMARKS = 33

// ---------------------------------------------------------------------------
// Synthetic data generators
// ---------------------------------------------------------------------------

function generateSyntheticLandmarks(frameCount, offset = 0) {
  const baseX = [
    0.50, 0.50, 0.52, 0.48, 0.54, 0.46, 0.55, 0.45,
    0.56, 0.44, 0.57, 0.43,
    0.60, 0.40, 0.65, 0.35, 0.68, 0.32,
    0.62, 0.38, 0.63, 0.37,
    0.61, 0.39,
    0.58, 0.42, 0.56, 0.44, 0.57, 0.43,
    0.56, 0.44, 0.57, 0.43, 0.50,
  ]
  const baseY = [
    0.10, 0.10, 0.11, 0.11, 0.10, 0.10, 0.12, 0.12,
    0.11, 0.11, 0.13, 0.13,
    0.25, 0.25, 0.40, 0.40, 0.55, 0.55,
    0.58, 0.58, 0.56, 0.56,
    0.55, 0.55,
    0.55, 0.55, 0.70, 0.70, 0.85, 0.85,
    0.88, 0.88, 0.90, 0.90, 0.08,
  ]

  const landmarks = []
  for (let f = 0; f < frameCount; f++) {
    const t = f / frameCount
    const swing = Math.sin(t * Math.PI * 2) * 0.03
    const frame = []
    for (let i = 0; i < NUM_LANDMARKS; i++) {
      const bx = baseX[i] ?? 0.5
      const by = baseY[i] ?? 0.5
      frame.push([
        Math.min(0.95, Math.max(0.05, bx + swing * (i > 15 ? 1.5 : 0.5) + offset * 0.06)),
        Math.min(0.95, Math.max(0.05, by + Math.sin(t * Math.PI * 4 + i * 0.15) * 0.01)),
        0,
      ])
    }
    landmarks.push(frame)
  }
  return landmarks
}

function generateSyntheticDeviations(frameCount) {
  const frames = [
    Math.floor(frameCount * 0.25),
    Math.floor(frameCount * 0.50),
    Math.floor(frameCount * 0.75),
  ]
  const severities = ['moderate', 'critical', 'minor']
  return frames.map((fi, i) => ({
    frame_index: fi,
    phase: 'forward_swing',
    severity: severities[i],
    deviating_joints: [
      {
        joint_name: 'elbow_angle',
        landmark_indices: [13, 14],
        user_angle: 95 + i * 10,
        pro_angle: 80,
        diff_degrees: 15 + i * 10,
        direction: 'too_wide',
      },
    ],
  }))
}

function generateSyntheticPhaseBoundaries(frameCount) {
  const q = Math.floor(frameCount / 5)
  // Include tempo_ratio so PhaseTimeline can render tempo badges
  return {
    preparation:    { user_start: 0,       user_end: q - 1,       user_duration_frames: q,     pro_duration_frames: q,       tempo_ratio: 1.0  },
    backswing:      { user_start: q,        user_end: 2 * q - 1,   user_duration_frames: q,     pro_duration_frames: q - 2,   tempo_ratio: 1.2  },
    forward_swing:  { user_start: 2 * q,    user_end: 3 * q - 1,   user_duration_frames: q,     pro_duration_frames: q + 2,   tempo_ratio: 0.85 },
    contact:        { user_start: 3 * q,    user_end: 4 * q - 1,   user_duration_frames: q,     pro_duration_frames: q,       tempo_ratio: 1.0  },
    follow_through: { user_start: 4 * q,    user_end: frameCount - 1, user_duration_frames: frameCount - 4 * q, pro_duration_frames: frameCount - 4 * q, tempo_ratio: 0.95 },
  }
}

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

export default function DevOverlayTest() {
  const [showUser, setShowUser] = useState(true)
  const [showPro, setShowPro] = useState(true)
  const [showDeviations, setShowDeviations] = useState(true)

  const userLandmarks = useMemo(() => generateSyntheticLandmarks(NUM_FRAMES, 0), [])
  const proLandmarks = useMemo(() => generateSyntheticLandmarks(NUM_FRAMES, 1), [])
  const frameDeviations = useMemo(() => generateSyntheticDeviations(NUM_FRAMES), [])
  const phaseBoundaries = useMemo(() => generateSyntheticPhaseBoundaries(NUM_FRAMES), [])

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
  } = useVideoPlayback({ totalFrames: NUM_FRAMES, fps: 30, phaseBoundaries })

  const currentDev = frameDeviations.find((d) => d.frame_index === currentFrame)

  return (
    <div className="space-y-6 pb-8">
      <div>
        <h1 className="text-2xl font-bold text-white">Overlay Canvas — Dev Test</h1>
        <p className="text-sm text-gray-400 mt-1">
          Synthetic data &bull; No real video &bull; Dev-mode only
        </p>
      </div>

      {/* Canvas */}
      <div className="flex flex-col items-start gap-3">
        <DualSkeletonCanvas
          videoSrc={null}
          userLandmarks={userLandmarks}
          proLandmarks={proLandmarks}
          frameDeviations={frameDeviations}
          landmarkConnections={LANDMARK_CONNECTIONS}
          phaseBoundaries={phaseBoundaries}
          fps={30}
          currentFrame={currentFrame}
          showUserSkeleton={showUser}
          showProSkeleton={showPro}
          showDeviations={showDeviations}
          width={640}
          height={360}
        />
        <SkeletonLegend />
      </div>

      {/* Video scrubber + transport controls */}
      <div className="rounded-xl border border-gray-800 bg-gray-900 p-4">
        <VideoScrubber
          totalFrames={NUM_FRAMES}
          currentFrame={currentFrame}
          onFrameChange={seekToFrame}
          fps={30}
          isPlaying={isPlaying}
          onPlayPause={togglePlayPause}
          onStepForward={stepForward}
          onStepBackward={stepBackward}
          phaseBoundaries={phaseBoundaries}
          playbackSpeed={playbackSpeed}
          onSpeedChange={setPlaybackSpeed}
          onSeekToPhase={seekToPhase}
        />
      </div>

      {/* Phase timeline */}
      <div className="rounded-xl border border-gray-800 bg-gray-900 p-4">
        <PhaseTimeline
          totalFrames={NUM_FRAMES}
          currentFrame={currentFrame}
          phaseBoundaries={phaseBoundaries}
          onSeekToPhase={seekToPhase}
        />
      </div>

      {/* Skeleton toggles */}
      <div className="flex gap-4 text-sm">
        <label className="flex items-center gap-2 cursor-pointer select-none">
          <input type="checkbox" checked={showUser} onChange={(e) => setShowUser(e.target.checked)} className="accent-[#00D4FF]" />
          <span className="text-[#00D4FF]">Your skeleton</span>
        </label>
        <label className="flex items-center gap-2 cursor-pointer select-none">
          <input type="checkbox" checked={showPro} onChange={(e) => setShowPro(e.target.checked)} className="accent-[#FFD700]" />
          <span className="text-[#FFD700]">Pro skeleton</span>
        </label>
        <label className="flex items-center gap-2 cursor-pointer select-none">
          <input type="checkbox" checked={showDeviations} onChange={(e) => setShowDeviations(e.target.checked)} className="accent-[#EF4444]" />
          <span className="text-[#EF4444]">Deviations</span>
        </label>
      </div>

      {/* Current frame info */}
      <div className="rounded-xl border border-gray-800 bg-gray-900 p-4 text-sm">
        <p className="text-xs font-semibold uppercase tracking-widest text-gray-500 mb-2">
          Frame {currentFrame} — Deviation status
        </p>
        {currentDev ? (
          <div>
            <span
              className="inline-block px-2 py-0.5 rounded text-xs font-semibold mr-2"
              style={{
                background: currentDev.severity === 'critical' ? '#7f1d1d' : currentDev.severity === 'moderate' ? '#78350f' : '#1e3a5f',
                color: currentDev.severity === 'critical' ? '#ef4444' : currentDev.severity === 'moderate' ? '#f59e0b' : '#3b82f6',
              }}
            >
              {currentDev.severity}
            </span>
            {currentDev.deviating_joints.map((jd, i) => (
              <span key={i} className="text-gray-300">
                {jd.joint_name}: {Math.round(jd.diff_degrees)}° off
              </span>
            ))}
          </div>
        ) : (
          <p className="text-gray-500">No deviation at this frame</p>
        )}
        <p className="text-gray-600 text-xs mt-2">
          Deviation frames: {frameDeviations.map((d) => d.frame_index).join(', ')}
        </p>
      </div>
    </div>
  )
}
