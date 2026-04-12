import { useRef, useEffect, useCallback, useMemo } from 'react'
import { transformLandmarks, transformLandmarksAligned, getDeviationsForFrame, getCurrentPhase, detectHandedness } from '../lib/landmarks'

// ---------------------------------------------------------------------------
// Color palette
// ---------------------------------------------------------------------------
const USER_COLOR = '#00D4FF'
const PRO_COLOR  = '#FFD700'
const SEVERITY_COLOR = {
  critical: '#EF4444',
  moderate: '#F59E0B',
  minor:    '#3B82F6',
}
const SEVERITY_LINE_WIDTH = { critical: 3, moderate: 2, minor: 1.5 }

// Phase border colors — match PHASE_COLORS in VideoScrubber
const PHASE_BORDER = {
  preparation:    '#4b5563',
  backswing:      '#1d4ed8',
  forward_swing:  '#15803d',
  contact:        '#ca8a04',
  follow_through: '#7c3aed',
}

// Fade speed: fraction of remaining distance closed per frame (~16ms)
const FADE_RATE = 0.15

// ---------------------------------------------------------------------------
// Pure canvas drawing helpers
// ---------------------------------------------------------------------------

function drawSkeleton(ctx, coords, connections, color, dashed, alpha) {
  if (!coords.length || alpha < 0.01) return
  ctx.save()
  ctx.globalAlpha = 0.7 * alpha
  ctx.strokeStyle = color
  ctx.fillStyle = color
  ctx.lineWidth = 2
  ctx.setLineDash(dashed ? [6, 3] : [])
  ctx.lineCap = 'round'

  ctx.beginPath()
  for (const [a, b] of connections) {
    const ca = coords[a]
    const cb = coords[b]
    if (!ca || !cb) continue
    ctx.moveTo(ca[0], ca[1])
    ctx.lineTo(cb[0], cb[1])
  }
  ctx.stroke()

  // Draw joint dots, skipping hand (17-22) and foot index (31-32) landmarks
  // that aren't skeleton connection endpoints and add visual clutter
  const SKIP_DOTS = new Set([17, 18, 19, 20, 21, 22, 31, 32])
  ctx.setLineDash([])
  ctx.globalAlpha = 0.85 * alpha
  for (let i = 0; i < coords.length; i++) {
    if (SKIP_DOTS.has(i) || !coords[i]) continue
    ctx.beginPath()
    ctx.arc(coords[i][0], coords[i][1], 4, 0, 2 * Math.PI)
    ctx.fill()
  }

  ctx.restore()
}

// Dominant-hand wrist/elbow pairs (BlazePose indices)
const HAND_INDICES = {
  right: [16, 14],  // right wrist, right elbow
  left:  [15, 13],  // left wrist, left elbow
}

/**
 * Draw racquet as a line extending from the dominant wrist along the forearm direction.
 * Length = 2x the forearm (elbow→wrist) distance.
 */
function drawRacquet(ctx, coords, color, alpha, handedness) {
  if (!coords.length || alpha < 0.01) return
  const [wristIdx, elbowIdx] = HAND_INDICES[handedness] || HAND_INDICES.right

  const wrist = coords[wristIdx]
  const elbow = coords[elbowIdx]
  if (!wrist || !elbow) return

  const dx = wrist[0] - elbow[0]
  const dy = wrist[1] - elbow[1]
  const forearmLen = Math.sqrt(dx * dx + dy * dy)
  if (forearmLen < 1) return

  ctx.save()
  ctx.globalAlpha = 0.85 * alpha
  ctx.strokeStyle = color
  ctx.lineWidth = 6
  ctx.lineCap = 'round'

  ctx.beginPath()
  ctx.moveTo(wrist[0], wrist[1])
  ctx.lineTo(wrist[0] + dx * 2, wrist[1] + dy * 2)
  ctx.stroke()
  ctx.restore()
}

function drawDeviationHighlights(ctx, coords, frameDevs, pulseAngle) {
  const pulse = 0.5 + 0.5 * Math.sin(pulseAngle)

  for (const dev of frameDevs) {
    const color = SEVERITY_COLOR[dev.severity] || SEVERITY_COLOR.moderate
    const lw = SEVERITY_LINE_WIDTH[dev.severity] || 2
    const isCritical = dev.severity === 'critical'
    // Critical deviations pulse more aggressively
    const effectivePulse = isCritical ? 0.4 + 0.6 * Math.sin(pulseAngle * 1.5) : pulse

    for (const jd of dev.deviating_joints || []) {
      for (const idx of jd.landmark_indices || []) {
        const coord = coords[idx]
        if (!coord) continue
        const [x, y] = coord
        const radius = 12 + 6 * effectivePulse

        ctx.save()
        ctx.shadowColor = color
        ctx.shadowBlur = isCritical ? 24 : 18
        ctx.beginPath()
        ctx.arc(x, y, radius, 0, 2 * Math.PI)
        ctx.strokeStyle = color
        ctx.lineWidth = lw
        ctx.globalAlpha = 0.75 + 0.25 * effectivePulse
        ctx.stroke()
        ctx.restore()
      }

      const firstIdx = jd.landmark_indices?.[0]
      if (firstIdx != null && coords[firstIdx] != null && jd.diff_degrees != null) {
        const [lx, ly] = coords[firstIdx]
        const label = `${Math.round(jd.diff_degrees)}°`
        ctx.save()
        ctx.font = 'bold 11px monospace'
        ctx.globalAlpha = 1.0
        ctx.shadowColor = 'rgba(0,0,0,0.8)'
        ctx.shadowBlur = 4
        ctx.fillStyle = color
        ctx.fillText(label, lx + 16, ly - 8)
        ctx.restore()
      }
    }
  }
}

/**
 * Linearly interpolate between two landmark frames.
 * Each frame is an array of [x, y, z] arrays (one per landmark).
 * Returns a new frame with blended positions.
 */
function lerpLandmarks(frameA, frameB, t) {
  if (!frameA || !frameB) return frameA || frameB || null
  const out = []
  for (let i = 0; i < frameA.length; i++) {
    const a = frameA[i]
    const b = frameB[i]
    if (!a || !b) { out.push(a || b || null); continue }
    out.push([
      a[0] + (b[0] - a[0]) * t,
      a[1] + (b[1] - a[1]) * t,
      a[2] + (b[2] - a[2]) * t,
    ])
  }
  return out
}

function drawPhaseLabel(ctx, phaseName) {
  if (!phaseName) return
  ctx.save()
  ctx.font = 'bold 12px sans-serif'
  const textWidth = ctx.measureText(phaseName).width
  ctx.fillStyle = 'rgba(0, 0, 0, 0.55)'
  ctx.beginPath()
  ctx.roundRect(8, 8, textWidth + 16, 26, 6)
  ctx.fill()
  ctx.fillStyle = '#ffffff'
  ctx.globalAlpha = 0.9
  ctx.fillText(phaseName, 16, 26)
  ctx.restore()
}

function drawFrameCounter(ctx, currentFrame, totalFrames, width) {
  if (totalFrames <= 0) return
  const label = `F ${currentFrame}/${totalFrames - 1}`
  ctx.save()
  ctx.font = '10px monospace'
  ctx.globalAlpha = 0.7
  const textWidth = ctx.measureText(label).width
  // Background pill in top-right
  ctx.fillStyle = 'rgba(0, 0, 0, 0.5)'
  ctx.beginPath()
  ctx.roundRect(width - textWidth - 24, 8, textWidth + 16, 20, 4)
  ctx.fill()
  ctx.fillStyle = '#d1d5db'
  ctx.fillText(label, width - textWidth - 16, 22)
  ctx.restore()
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export default function DualSkeletonCanvas({
  videoSrc,
  userLandmarks,
  proLandmarks,
  canonicalLandmarks = null,  // angle-normalized 2D landmarks (from 3D canonicalization)
  useCanonicalView = false,   // when true, render canonical landmarks instead of raw user landmarks
  frameDeviations,
  landmarkConnections,
  phaseBoundaries,
  fps = 30,
  currentFrame = 0,
  showUserSkeleton = true,
  showProSkeleton = true,
  showDeviations = true,
  alignSkeletons = false,
  racquetConnections = null,
  racquetData = null,
  proRacquetData = null,
  frameProgress = 0,
  isPlaying = false,
  playbackSpeed = 1.0,
  detectionMask = null,
  anchorTo = 'user',  // 'user' or 'pro' — which skeleton stays at its natural video position
  width = 640,
  height = 360,
  videoTimeSeconds = null,  // when set, overrides currentFrame/fps for video seek (used for pro video)
}) {
  const canvasRef = useRef(null)
  const offscreenRef = useRef(null)
  const videoRef = useRef(null)
  const rafRef = useRef(null)
  const smoothedAlignRef = useRef(null)

  // Fade state: current rendered alpha for each skeleton (0–1)
  const userAlphaRef = useRef(showUserSkeleton ? 1 : 0)
  const proAlphaRef  = useRef(showProSkeleton  ? 1 : 0)

  // Sub-frame interpolation computed directly in the rAF loop (bypasses React)
  const localProgressRef = useRef(0)
  const lastRafTimeRef = useRef(null)

  const renderRef = useRef(null)

  // When canonical view is active and data is available, swap in canonical landmarks
  const effectiveUserLandmarks = (useCanonicalView && canonicalLandmarks) ? canonicalLandmarks : userLandmarks

  const totalFrames = effectiveUserLandmarks?.length ?? (proLandmarks?.length ?? 0)

  // Detect handedness once from all-frames wrist displacement
  const userHand = useMemo(() => detectHandedness(effectiveUserLandmarks), [effectiveUserLandmarks])
  const proHand  = useMemo(() => detectHandedness(proLandmarks),  [proLandmarks])

  const render = useCallback(() => {
    const canvas = canvasRef.current
    if (!canvas) return

    // Lazy-init offscreen canvas for double buffering (avoids flashing)
    if (!offscreenRef.current || offscreenRef.current.width !== width || offscreenRef.current.height !== height) {
      offscreenRef.current = new OffscreenCanvas(width, height)
    }
    const ctx = offscreenRef.current.getContext('2d')

    // Clear to transparent - the video element renders underneath via CSS layering.
    // When there's no video, the parent container's dark background shows through.
    ctx.clearRect(0, 0, width, height)

    // Skip user skeleton on frames where pose was not detected (interpolated
    // data from large gaps produces garbage landmarks).
    const frameDetected = !detectionMask || detectionMask[currentFrame] !== false
    const nextFrame = currentFrame + 1
    const t = localProgressRef.current
    const hasNext = t > 0.001 && nextFrame < (effectiveUserLandmarks?.length ?? 0)
    const nextDetected = !detectionMask || detectionMask[nextFrame] !== false

    // Interpolate between current and next frame for smooth playback
    let userLm, proLm
    if (hasNext && frameDetected && nextDetected) {
      userLm = lerpLandmarks(effectiveUserLandmarks?.[currentFrame], effectiveUserLandmarks?.[nextFrame], t)
      proLm = lerpLandmarks(proLandmarks?.[currentFrame], proLandmarks?.[nextFrame], t)
    } else {
      userLm = frameDetected ? effectiveUserLandmarks?.[currentFrame] : null
      proLm = proLandmarks?.[currentFrame]
    }
    const frameDevs = getDeviationsForFrame(frameDeviations, currentFrame)
    const phaseName = getCurrentPhase(phaseBoundaries, currentFrame)

    let userCoords, proCoords
    if (alignSkeletons && (userLm || proLm)) {
      const aligned = transformLandmarksAligned(userLm, proLm, width, height, smoothedAlignRef, anchorTo)
      userCoords = aligned.userCoords
      proCoords = aligned.proCoords
    } else {
      smoothedAlignRef.current = null
      userCoords = userLm ? transformLandmarks(userLm, width, height) : []
      proCoords  = proLm  ? transformLandmarks(proLm,  width, height) : []
    }

    // Advance fade values toward their targets
    const userTarget = showUserSkeleton ? 1 : 0
    const proTarget  = showProSkeleton  ? 1 : 0
    userAlphaRef.current += (userTarget - userAlphaRef.current) * FADE_RATE
    proAlphaRef.current  += (proTarget  - proAlphaRef.current)  * FADE_RATE

    // Pro skeleton (behind user)
    if (proCoords.length) {
      drawSkeleton(ctx, proCoords, landmarkConnections || [], PRO_COLOR, true, proAlphaRef.current)
      drawRacquet(ctx, proCoords, PRO_COLOR, proAlphaRef.current, proHand)
    }

    // User skeleton on top
    if (userCoords.length) {
      drawSkeleton(ctx, userCoords, landmarkConnections || [], USER_COLOR, false, userAlphaRef.current)
      drawRacquet(ctx, userCoords, USER_COLOR, userAlphaRef.current, userHand)
    }

    // Deviation highlights disabled in canvas — shown in the panel below instead

    // Phase label (top-left)
    drawPhaseLabel(ctx, phaseName)

    // Frame counter (top-right)
    drawFrameCounter(ctx, currentFrame, totalFrames, width)

    // Blit offscreen canvas to visible canvas in one operation (no flicker)
    const visibleCtx = canvas.getContext('2d')
    visibleCtx.clearRect(0, 0, width, height)
    visibleCtx.drawImage(offscreenRef.current, 0, 0)
  }, [
    effectiveUserLandmarks, proLandmarks, frameDeviations, landmarkConnections, racquetConnections,
    phaseBoundaries, currentFrame, showUserSkeleton, showProSkeleton,
    showDeviations, alignSkeletons, anchorTo, detectionMask, width, height, totalFrames,
    userHand, proHand,
  ])

  useEffect(() => { renderRef.current = render }, [render])

  // Reset smoothing when anchor direction changes to avoid stale offsets
  useEffect(() => { smoothedAlignRef.current = null }, [anchorTo])

  // Reset sub-frame progress when frame changes (e.g., scrubbing, stepping)
  useEffect(() => {
    localProgressRef.current = frameProgress
    lastRafTimeRef.current = null
  }, [currentFrame, frameProgress])

  // rAF loop — advances sub-frame interpolation directly (no React state)
  useEffect(() => {
    function loop(timestamp) {
      if (isPlaying && lastRafTimeRef.current != null) {
        const dt = timestamp - lastRafTimeRef.current
        const advance = (dt / 1000) * fps * playbackSpeed
        localProgressRef.current = Math.min(localProgressRef.current + advance, 0.999)
      }
      lastRafTimeRef.current = timestamp
      renderRef.current?.()
      rafRef.current = requestAnimationFrame(loop)
    }
    rafRef.current = requestAnimationFrame(loop)
    return () => cancelAnimationFrame(rafRef.current)
  }, [isPlaying, fps, playbackSpeed])

  // Video playback strategy:
  // - High speed (effective fps > 60): use native video.play() because the
  //   browser can't seek fast enough at 60+ seeks/sec. Drift-correct only
  //   when the video falls significantly out of sync.
  // - Low speed (effective fps <= 60): seek frame-by-frame so video frames
  //   stay perfectly synchronized with skeleton animation. At 0.25x with
  //   120fps landmarks, that's only 30 seeks/sec which browsers handle fine.
  //   Native playback at low rates causes visible lag because the browser
  //   holds each decoded frame longer while the skeleton interpolates smoothly.
  const useNativeVideo = isPlaying && fps * playbackSpeed > 60

  useEffect(() => {
    const video = videoRef.current
    if (!video || !videoSrc) return

    if (useNativeVideo) {
      video.playbackRate = playbackSpeed
      const targetTime = videoTimeSeconds != null ? videoTimeSeconds : currentFrame / fps
      if (Math.abs(video.currentTime - targetTime) > 0.5 / fps) {
        video.currentTime = targetTime
      }
      video.play().catch(() => {})
    } else {
      video.pause()
    }
  }, [useNativeVideo, playbackSpeed, videoSrc]) // eslint-disable-line react-hooks/exhaustive-deps

  // Sync video position with skeleton frame.
  useEffect(() => {
    const video = videoRef.current
    if (!video || !videoSrc || fps <= 0) return

    const targetTime = videoTimeSeconds != null ? videoTimeSeconds : currentFrame / fps

    if (useNativeVideo) {
      // Native playback: only correct large drift (> 0.15s)
      if (Math.abs(video.currentTime - targetTime) > 0.15) {
        video.currentTime = targetTime
      }
    } else {
      // Frame-by-frame seeking (paused or slow speed)
      if (Math.abs(video.currentTime - targetTime) > 0.5 / fps) {
        video.currentTime = targetTime
      }
    }
  }, [currentFrame, fps, videoSrc, videoTimeSeconds, useNativeVideo])

  // Derive phase name for the border color (raw key, not formatted)
  let currentPhaseKey = null
  if (phaseBoundaries) {
    for (const [name, b] of Object.entries(phaseBoundaries)) {
      const start = b.user_start ?? b.start ?? 0
      const end   = b.user_end   ?? b.end   ?? 0
      if (currentFrame >= start && currentFrame <= end) {
        currentPhaseKey = name
        break
      }
    }
  }
  const borderColor = PHASE_BORDER[currentPhaseKey] || '#374151'

  return (
    <div
      className="relative inline-block rounded-lg overflow-hidden"
      style={{
        boxShadow: `0 0 0 2px ${borderColor}`,
        transition: 'box-shadow 0.3s ease',
        width, height,
        background: '#0f172a',
      }}
    >
      {videoSrc && (
        <video
          ref={videoRef}
          src={videoSrc}
          style={{ position: 'absolute', top: 0, left: 0, width: '100%', height: '100%', objectFit: 'fill' }}
          playsInline
          muted
          preload="auto"
          crossOrigin="anonymous"
        />
      )}
      <canvas
        ref={canvasRef}
        width={width}
        height={height}
        className="block"
        style={{ position: 'relative', zIndex: 1 }}
      />
    </div>
  )
}
