/**
 * Utilities for landmark coordinate transformation and per-frame deviation lookup.
 */

// MediaPipe BlazePose landmark indices
const LEFT_HIP = 23
const RIGHT_HIP = 24
const LEFT_SHOULDER = 11
const RIGHT_SHOULDER = 12

// Default alignment target: center of normalized space, standard torso size
const DEFAULT_TARGET_CENTER = [0.5, 0.5]
const DEFAULT_TARGET_SCALE = 0.25

// Exponential smoothing factor (0 = no smoothing, 1 = no memory)
const SMOOTH_ALPHA = 0.15

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
 * Compute hip center and torso length for a single frame's landmarks.
 * Returns null if required landmarks are missing.
 */
export function computeAlignmentParams(landmarks) {
  if (!landmarks || landmarks.length < 25) return null

  const lh = landmarks[LEFT_HIP]
  const rh = landmarks[RIGHT_HIP]
  const ls = landmarks[LEFT_SHOULDER]
  const rs = landmarks[RIGHT_SHOULDER]

  if (!lh || !rh || !ls || !rs) return null

  const hipCenter = [(lh[0] + rh[0]) / 2, (lh[1] + rh[1]) / 2]
  const shoulderCenter = [(ls[0] + rs[0]) / 2, (ls[1] + rs[1]) / 2]

  const dx = shoulderCenter[0] - hipCenter[0]
  const dy = shoulderCenter[1] - hipCenter[1]
  const torsoLength = Math.sqrt(dx * dx + dy * dy)

  if (torsoLength < 0.001) return null

  return { hipCenter, torsoLength }
}

/**
 * Translate and scale landmarks so the hip center moves to targetCenter
 * and the torso length matches targetScale.
 */
export function alignLandmarks(landmarks, hipCenter, torsoLength, targetCenter, targetScale) {
  const scale = targetScale / torsoLength
  return landmarks.map(([x, y, z]) => [
    (x - hipCenter[0]) * scale + targetCenter[0],
    (y - hipCenter[1]) * scale + targetCenter[1],
    z ?? 0,
  ])
}

/**
 * Align both user and pro landmarks, apply smoothing, and convert to pixel coords.
 *
 * smoothedRef.current should be { user: {hipCenter, torsoLength}, pro: {hipCenter, torsoLength} }
 * or null on first call. It is mutated in place for cross-frame smoothing.
 */
export function transformLandmarksAligned(userLm, proLm, canvasWidth, canvasHeight, smoothedRef) {
  const userParams = userLm ? computeAlignmentParams(userLm) : null
  const proParams = proLm ? computeAlignmentParams(proLm) : null

  // If we can't compute params for either, fall back to raw transform
  if (!userParams && !proParams) {
    return {
      userCoords: userLm ? transformLandmarks(userLm, canvasWidth, canvasHeight) : [],
      proCoords: proLm ? transformLandmarks(proLm, canvasWidth, canvasHeight) : [],
    }
  }

  // Smooth params across frames to prevent jitter
  const prev = smoothedRef.current
  if (prev) {
    for (const key of ['user', 'pro']) {
      const raw = key === 'user' ? userParams : proParams
      if (raw && prev[key]) {
        raw.hipCenter[0] = prev[key].hipCenter[0] + SMOOTH_ALPHA * (raw.hipCenter[0] - prev[key].hipCenter[0])
        raw.hipCenter[1] = prev[key].hipCenter[1] + SMOOTH_ALPHA * (raw.hipCenter[1] - prev[key].hipCenter[1])
        raw.torsoLength = prev[key].torsoLength + SMOOTH_ALPHA * (raw.torsoLength - prev[key].torsoLength)
      }
    }
  }
  smoothedRef.current = { user: userParams, pro: proParams }

  const tc = DEFAULT_TARGET_CENTER
  const ts = DEFAULT_TARGET_SCALE

  const userAligned = userParams
    ? alignLandmarks(userLm, userParams.hipCenter, userParams.torsoLength, tc, ts)
    : userLm
  const proAligned = proParams
    ? alignLandmarks(proLm, proParams.hipCenter, proParams.torsoLength, tc, ts)
    : proLm

  return {
    userCoords: userAligned ? userAligned.map(([x, y]) => [x * canvasWidth, y * canvasHeight]) : [],
    proCoords: proAligned ? proAligned.map(([x, y]) => [x * canvasWidth, y * canvasHeight]) : [],
  }
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
 * Get the stance width deviation value for a specific frame.
 * Returns the diff_degrees value (normalized distance diff: user - pro)
 * for the "stance_width" joint, or null if no stance deviation on that frame.
 *
 * @param {Object[]} frameDeviations  Array from the overlay API response
 * @param {number} frameIndex
 * @returns {number|null}
 */
export function getStanceWidthDeviation(frameDeviations, frameIndex) {
  if (!frameDeviations?.length) return null
  for (const fd of frameDeviations) {
    if (fd.frame_index !== frameIndex) continue
    const stanceDev = fd.deviating_joints?.find((jd) => jd.joint_name === 'stance_width')
    if (stanceDev != null) return stanceDev.diff_degrees
  }
  return null
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
