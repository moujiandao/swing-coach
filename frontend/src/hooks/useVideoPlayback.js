import { useState, useRef, useCallback, useEffect } from 'react'

/**
 * useVideoPlayback
 *
 * Manages frame-level playback state for the overlay canvas.
 * Uses requestAnimationFrame to advance frames at `fps * playbackSpeed`,
 * looping back to frame 0 when the end is reached.
 *
 * The parent is responsible for passing `currentFrame` to DualSkeletonCanvas
 * and to any scrubber UI.
 */
export function useVideoPlayback({ totalFrames = 1, fps = 30, phaseBoundaries = null } = {}) {
  // Track fractional frame position for smooth interpolation during playback.
  // currentFrame is the integer frame (for scrubber/UI), frameProgress is the
  // fractional part (0-1) between currentFrame and currentFrame+1.
  const [currentFrame, setCurrentFrame] = useState(0)
  const [frameProgress, setFrameProgress] = useState(0)
  const [isPlaying, setIsPlaying] = useState(false)
  const [playbackSpeed, setPlaybackSpeed] = useState(0.25)

  // Always-current config for the RAF loop to read without stale closures
  const configRef = useRef({ fps, playbackSpeed, totalFrames })
  configRef.current = { fps, playbackSpeed, totalFrames }

  // Accumulated fractional frame position (avoids stale closure issues)
  const positionRef = useRef(0)

  const rafRef = useRef(null)

  // Playback loop — started/stopped when isPlaying flips
  useEffect(() => {
    if (!isPlaying) return

    let lastTimestamp = null

    function loop(timestamp) {
      if (lastTimestamp === null) {
        lastTimestamp = timestamp
        rafRef.current = requestAnimationFrame(loop)
        return
      }

      const { fps: currentFps, playbackSpeed: currentSpeed, totalFrames: total } = configRef.current
      const elapsed = timestamp - lastTimestamp
      lastTimestamp = timestamp

      // Advance by fractional frames based on elapsed time
      const framesAdvanced = (elapsed / 1000) * currentFps * currentSpeed
      positionRef.current += framesAdvanced

      if (positionRef.current >= total) {
        positionRef.current = 0
      }

      const intFrame = Math.floor(positionRef.current)
      const frac = positionRef.current - intFrame
      setCurrentFrame(intFrame)
      setFrameProgress(frac)

      rafRef.current = requestAnimationFrame(loop)
    }

    rafRef.current = requestAnimationFrame(loop)
    return () => cancelAnimationFrame(rafRef.current)
  }, [isPlaying])

  const togglePlayPause = useCallback(() => setIsPlaying((p) => !p), [])

  const seekToFrame = useCallback(
    (frame) => {
      const clamped = Math.max(0, Math.min(Math.round(frame), totalFrames - 1))
      positionRef.current = clamped
      setCurrentFrame(clamped)
      setFrameProgress(0)
    },
    [totalFrames],
  )

  const seekToPhase = useCallback(
    (phaseName) => {
      const boundary = phaseBoundaries?.[phaseName]
      if (boundary != null) {
        seekToFrame(boundary.user_start ?? 0)
      }
    },
    [phaseBoundaries, seekToFrame],
  )

  const stepForward = useCallback(() => {
    setCurrentFrame((f) => {
      const next = Math.min(f + 1, totalFrames - 1)
      positionRef.current = next
      setFrameProgress(0)
      return next
    })
  }, [totalFrames])

  const stepBackward = useCallback(() => {
    setCurrentFrame((f) => {
      const prev = Math.max(f - 1, 0)
      positionRef.current = prev
      setFrameProgress(0)
      return prev
    })
  }, [])

  return {
    currentFrame,
    frameProgress,
    isPlaying,
    playbackSpeed,
    setPlaybackSpeed,
    togglePlayPause,
    seekToFrame,
    seekToPhase,
    stepForward,
    stepBackward,
  }
}
