import { useRef, useEffect, useCallback } from 'react'
import { transformLandmarks, getDeviationsForFrame, getCurrentPhase } from '../lib/landmarks'

// ---------------------------------------------------------------------------
// Color palette
// ---------------------------------------------------------------------------
const USER_COLOR = '#00D4FF'   // cyan
const PRO_COLOR = '#FFD700'    // gold
const SEVERITY_COLOR = {
  critical: '#EF4444',
  moderate: '#F59E0B',
  minor: '#3B82F6',
}
const SEVERITY_LINE_WIDTH = { critical: 3, moderate: 2, minor: 1.5 }

// ---------------------------------------------------------------------------
// Pure canvas drawing helpers
// ---------------------------------------------------------------------------

function drawSkeleton(ctx, coords, connections, color, dashed) {
  if (!coords.length) return
  ctx.save()
  ctx.globalAlpha = 0.7
  ctx.strokeStyle = color
  ctx.fillStyle = color
  ctx.lineWidth = 2
  ctx.setLineDash(dashed ? [6, 3] : [])
  ctx.lineCap = 'round'

  // Bones
  ctx.beginPath()
  for (const [a, b] of connections) {
    const ca = coords[a]
    const cb = coords[b]
    if (!ca || !cb) continue
    ctx.moveTo(ca[0], ca[1])
    ctx.lineTo(cb[0], cb[1])
  }
  ctx.stroke()

  // Landmark dots
  ctx.setLineDash([])
  ctx.globalAlpha = 0.85
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

    for (const jd of dev.deviating_joints || []) {
      // Glow circle on each landmark of this joint
      for (const idx of jd.landmark_indices || []) {
        const coord = coords[idx]
        if (!coord) continue
        const [x, y] = coord
        const radius = 12 + 5 * pulse

        ctx.save()
        ctx.shadowColor = color
        ctx.shadowBlur = 18
        ctx.beginPath()
        ctx.arc(x, y, radius, 0, 2 * Math.PI)
        ctx.strokeStyle = color
        ctx.lineWidth = lw
        ctx.globalAlpha = 0.75 + 0.25 * pulse
        ctx.stroke()
        ctx.restore()
      }

      // Angle diff label at the first landmark of this joint
      const firstIdx = jd.landmark_indices?.[0]
      if (firstIdx != null && coords[firstIdx] != null && jd.diff_degrees != null) {
        const [lx, ly] = coords[firstIdx]
        const label = `${Math.round(jd.diff_degrees)}°`
        ctx.save()
        ctx.font = 'bold 11px monospace'
        ctx.globalAlpha = 1.0
        // Shadow for readability on any background
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
  // Background pill
  ctx.fillStyle = 'rgba(0, 0, 0, 0.55)'
  ctx.beginPath()
  ctx.roundRect(8, 8, textWidth + 16, 26, 6)
  ctx.fill()
  // Label
  ctx.fillStyle = '#ffffff'
  ctx.globalAlpha = 0.9
  ctx.fillText(phaseName, 16, 26)
  ctx.restore()
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

/**
 * DualSkeletonCanvas
 *
 * Renders a user swing skeleton (cyan) and a pro reference skeleton (gold dashed)
 * on top of the user's video frame, with deviation highlighting and phase label.
 *
 * The parent controls `currentFrame` — this component just draws what it's told.
 */
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

  // Build a stable render function so the rAF loop can always call the latest version
  const renderRef = useRef(null)

  const render = useCallback(() => {
    const canvas = canvasRef.current
    if (!canvas) return
    const ctx = canvas.getContext('2d')

    // Dark background
    ctx.fillStyle = '#0f172a'
    ctx.fillRect(0, 0, width, height)

    // Video frame (drawn if video is seeked and has data)
    const video = videoRef.current
    if (video && video.readyState >= 2) {
      ctx.drawImage(video, 0, 0, width, height)
    }

    const userLm = userLandmarks?.[currentFrame]
    const proLm = proLandmarks?.[currentFrame]
    const frameDevs = getDeviationsForFrame(frameDeviations, currentFrame)
    const phaseName = getCurrentPhase(phaseBoundaries, currentFrame)

    const userCoords = userLm ? transformLandmarks(userLm, width, height) : []
    const proCoords = proLm ? transformLandmarks(proLm, width, height) : []

    // Pro skeleton first (behind user)
    if (showProSkeleton && proCoords.length) {
      drawSkeleton(ctx, proCoords, landmarkConnections || [], PRO_COLOR, true)
    }

    // User skeleton on top
    if (showUserSkeleton && userCoords.length) {
      drawSkeleton(ctx, userCoords, landmarkConnections || [], USER_COLOR, false)
    }

    // Deviation highlights (on user joints)
    if (showDeviations && userCoords.length && frameDevs.length) {
      drawDeviationHighlights(ctx, userCoords, frameDevs, pulseRef.current)
    }

    // Phase label
    drawPhaseLabel(ctx, phaseName)
  }, [
    userLandmarks, proLandmarks, frameDeviations, landmarkConnections,
    phaseBoundaries, currentFrame, showUserSkeleton, showProSkeleton,
    showDeviations, width, height,
  ])

  // Keep renderRef in sync so the rAF loop always calls the latest closure
  useEffect(() => {
    renderRef.current = render
  }, [render])

  // rAF loop — advances the pulse and calls render every frame
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
    // Only seek if we're more than half a frame away to avoid thrashing
    if (Math.abs(video.currentTime - targetTime) > 0.5 / fps) {
      video.currentTime = targetTime
    }
  }, [currentFrame, fps, videoSrc])

  return (
    <div className="relative inline-block">
      {/* Hidden video element used only as a texture source for canvas */}
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
        className="rounded-lg block"
        style={{ background: '#0f172a' }}
      />
    </div>
  )
}
