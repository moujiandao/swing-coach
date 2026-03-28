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
  const [currentFrame, setCurrentFrame] = useState(0)
  const [isPlaying, setIsPlaying] = useState(false)
  const [playbackSpeed, setPlaybackSpeed] = useState(1.0)

  // Always-current config for the RAF loop to read without stale closures
  const configRef = useRef({ fps, playbackSpeed, totalFrames })
  configRef.current = { fps, playbackSpeed, totalFrames }

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
      const msPerFrame = 1000 / (currentFps * currentSpeed)
      const elapsed = timestamp - lastTimestamp

      if (elapsed >= msPerFrame) {
        const frames = Math.floor(elapsed / msPerFrame)
        lastTimestamp = timestamp - (elapsed % msPerFrame)
        setCurrentFrame((prev) => {
          const next = prev + frames
          return next >= total ? 0 : next
        })
      }

      rafRef.current = requestAnimationFrame(loop)
    }

    rafRef.current = requestAnimationFrame(loop)
    return () => cancelAnimationFrame(rafRef.current)
  }, [isPlaying])

  const togglePlayPause = useCallback(() => setIsPlaying((p) => !p), [])

  const seekToFrame = useCallback(
    (frame) => {
      setCurrentFrame(Math.max(0, Math.min(Math.round(frame), totalFrames - 1)))
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
    setCurrentFrame((f) => Math.min(f + 1, totalFrames - 1))
  }, [totalFrames])

  const stepBackward = useCallback(() => {
    setCurrentFrame((f) => Math.max(f - 1, 0))
  }, [])

  return {
    currentFrame,
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
