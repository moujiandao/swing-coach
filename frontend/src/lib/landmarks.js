/**
 * Utilities for landmark coordinate transformation and per-frame deviation lookup.
 */

/**
 * Convert normalized [0–1] landmark coordinates to canvas pixel coordinates.
 *
 * MediaPipe returns landmarks as [x, y, z] with x,y in [0,1] relative to
 * frame dimensions. This scales them to actual canvas pixels.
 *
 * @param {number[][]} landmarks  Array of [x, y, z] triplets (one frame)
 * @param {number} canvasWidth
 * @param {number} canvasHeight
 * @returns {number[][]} Array of [px, py] pixel coordinates (z dropped)
 */
export function transformLandmarks(landmarks, canvasWidth, canvasHeight) {
  if (!landmarks) return []
  return landmarks.map(([x, y]) => [x * canvasWidth, y * canvasHeight])
}

/**
 * Get deviation annotation data for a specific frame index.
 *
 * @param {Object[]} frameDeviations  Array from the overlay API response
 * @param {number} frameIndex
 * @returns {Object[]}  Array of FrameDeviation objects that match this frame
 */
export function getDeviationsForFrame(frameDeviations, frameIndex) {
  if (!frameDeviations?.length) return []
  return frameDeviations.filter((d) => d.frame_index === frameIndex)
}

/**
 * Determine which phase name the given frame falls in.
 *
 * phaseBoundaries shape:  { phase_name: { user_start, user_end, ... } }
 *
 * @param {Object} phaseBoundaries
 * @param {number} frameIndex
 * @returns {string|null}  Formatted phase name, or null if not found
 */
export function getCurrentPhase(phaseBoundaries, frameIndex) {
  if (!phaseBoundaries) return null
  for (const [name, boundary] of Object.entries(phaseBoundaries)) {
    const start = boundary.user_start ?? boundary.start ?? 0
    const end = boundary.user_end ?? boundary.end ?? 0
    if (frameIndex >= start && frameIndex <= end) {
      return name.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase())
    }
  }
  return null
}
