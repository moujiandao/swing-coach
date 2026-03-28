import { useRef, useEffect, useCallback } from 'react'
import { transformLandmarks, getDeviationsForFrame, getCurrentPhase } from '../lib/landmarks'

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

  ctx.setLineDash([])
  ctx.globalAlpha = 0.85 * alpha
  for (const coord of coords) {
    if (!coord) continue
    ctx.beginPath()
    ctx.arc(coord[0], coord[1], 4, 0, 2 * Math.PI)
    ctx.fill()
  }

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
  frameDeviations,
  landmarkConnections,
  phaseBoundaries,
  fps = 30,
  currentFrame = 0,
  showUserSkeleton = true,
  showProSkeleton = true,
  showDeviations = true,
  width = 640,
  height = 360,
}) {
  const canvasRef = useRef(null)
  const videoRef = useRef(null)
  const pulseRef = useRef(0)
  const rafRef = useRef(null)

  // Fade state: current rendered alpha for each skeleton (0–1)
  const userAlphaRef = useRef(showUserSkeleton ? 1 : 0)
  const proAlphaRef  = useRef(showProSkeleton  ? 1 : 0)

  const renderRef = useRef(null)

  const totalFrames = userLandmarks?.length ?? (proLandmarks?.length ?? 0)

  const render = useCallback(() => {
    const canvas = canvasRef.current
    if (!canvas) return
    const ctx = canvas.getContext('2d')

    ctx.fillStyle = '#0f172a'
    ctx.fillRect(0, 0, width, height)

    const video = videoRef.current
    if (video && video.readyState >= 2) {
      ctx.drawImage(video, 0, 0, width, height)
    }

    const userLm   = userLandmarks?.[currentFrame]
    const proLm    = proLandmarks?.[currentFrame]
    const frameDevs = getDeviationsForFrame(frameDeviations, currentFrame)
    const phaseName = getCurrentPhase(phaseBoundaries, currentFrame)

    const userCoords = userLm ? transformLandmarks(userLm, width, height) : []
    const proCoords  = proLm  ? transformLandmarks(proLm,  width, height) : []

    // Advance fade values toward their targets
    const userTarget = showUserSkeleton ? 1 : 0
    const proTarget  = showProSkeleton  ? 1 : 0
    userAlphaRef.current += (userTarget - userAlphaRef.current) * FADE_RATE
    proAlphaRef.current  += (proTarget  - proAlphaRef.current)  * FADE_RATE

    // Pro skeleton (behind user)
    if (proCoords.length) {
      drawSkeleton(ctx, proCoords, landmarkConnections || [], PRO_COLOR, true, proAlphaRef.current)
    }

    // User skeleton on top
    if (userCoords.length) {
      drawSkeleton(ctx, userCoords, landmarkConnections || [], USER_COLOR, false, userAlphaRef.current)
    }

    // Deviation highlights
    if (showDeviations && userCoords.length && frameDevs.length) {
      drawDeviationHighlights(ctx, userCoords, frameDevs, pulseRef.current)
    }

    // Phase label (top-left)
    drawPhaseLabel(ctx, phaseName)

    // Frame counter (top-right)
    drawFrameCounter(ctx, currentFrame, totalFrames, width)
  }, [
    userLandmarks, proLandmarks, frameDeviations, landmarkConnections,
    phaseBoundaries, currentFrame, showUserSkeleton, showProSkeleton,
    showDeviations, width, height, totalFrames,
  ])

  useEffect(() => { renderRef.current = render }, [render])

  // rAF loop
  useEffect(() => {
    function loop() {
      pulseRef.current += 0.05
      renderRef.current?.()
      rafRef.current = requestAnimationFrame(loop)
    }
    rafRef.current = requestAnimationFrame(loop)
    return () => cancelAnimationFrame(rafRef.current)
  }, [])

  // Seek video when currentFrame changes
  useEffect(() => {
    const video = videoRef.current
    if (!video || !videoSrc || fps <= 0) return
    const targetTime = currentFrame / fps
    if (Math.abs(video.currentTime - targetTime) > 0.5 / fps) {
      video.currentTime = targetTime
    }
  }, [currentFrame, fps, videoSrc])

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
      }}
    >
      {videoSrc && (
        <video
          ref={videoRef}
          src={videoSrc}
          style={{ display: 'none' }}
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
        style={{ background: '#0f172a' }}
      />
    </div>
  )
}
