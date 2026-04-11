/**
 * Utilities for landmark coordinate transformation and per-frame deviation lookup.
 */

// MediaPipe BlazePose landmark indices
const LEFT_HIP = 23
const RIGHT_HIP = 24
const LEFT_SHOULDER = 11
const RIGHT_SHOULDER = 12
const LEFT_WRIST = 15
const RIGHT_WRIST = 16

// Default alignment target: center of normalized space, standard torso size
const DEFAULT_TARGET_CENTER = [0.5, 0.5]
const DEFAULT_TARGET_SCALE = 0.25

// Exponential smoothing factor (0 = no smoothing, 1 = no memory)
const SMOOTH_ALPHA = 0.4

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
 * Align pro skeleton onto the user's position, keeping natural scale.
 *
 * The user skeleton stays exactly where it is (matching the video). The pro
 * skeleton is translated so its hip center matches the user's, and scaled so
 * its torso length matches the user's. This keeps both skeletons at the
 * player's actual size and position in the frame.
 *
 * smoothedRef.current stores exponentially smoothed alignment offsets to
 * prevent jitter between frames.
 */
export function transformLandmarksAligned(userLm, proLm, canvasWidth, canvasHeight, smoothedRef, anchorTo = 'user') {
  const userParams = userLm ? computeAlignmentParams(userLm) : null
  const proParams = proLm ? computeAlignmentParams(proLm) : null

  // If we can't compute params for either, fall back to raw transform
  if (!userParams && !proParams) {
    return {
      userCoords: userLm ? transformLandmarks(userLm, canvasWidth, canvasHeight) : [],
      proCoords: proLm ? transformLandmarks(proLm, canvasWidth, canvasHeight) : [],
    }
  }

  // Smooth the user's hip center and torso length to prevent jitter
  const prev = smoothedRef.current
  if (prev && userParams && prev.user) {
    userParams.hipCenter[0] = prev.user.hipCenter[0] + SMOOTH_ALPHA * (userParams.hipCenter[0] - prev.user.hipCenter[0])
    userParams.hipCenter[1] = prev.user.hipCenter[1] + SMOOTH_ALPHA * (userParams.hipCenter[1] - prev.user.hipCenter[1])
    userParams.torsoLength = prev.user.torsoLength + SMOOTH_ALPHA * (userParams.torsoLength - prev.user.torsoLength)
  }
  if (prev && proParams && prev.pro) {
    proParams.hipCenter[0] = prev.pro.hipCenter[0] + SMOOTH_ALPHA * (proParams.hipCenter[0] - prev.pro.hipCenter[0])
    proParams.hipCenter[1] = prev.pro.hipCenter[1] + SMOOTH_ALPHA * (proParams.hipCenter[1] - prev.pro.hipCenter[1])
    proParams.torsoLength = prev.pro.torsoLength + SMOOTH_ALPHA * (proParams.torsoLength - prev.pro.torsoLength)
  }
  smoothedRef.current = { user: userParams, pro: proParams }

  // Determine anchor and guest based on anchorTo parameter
  let anchorParams = anchorTo === 'pro' ? proParams : userParams
  const anchorLm = anchorTo === 'pro' ? proLm : userLm
  let guestParams = anchorTo === 'pro' ? userParams : proParams
  const guestLm = anchorTo === 'pro' ? userLm : proLm

  // If anchor params are null this frame (e.g. detection gap), use last-known
  // smoothed values so the guest skeleton doesn't jump to its raw position
  if (!anchorParams && smoothedRef.current) {
    const prevAnchor = anchorTo === 'pro' ? smoothedRef.current.pro : smoothedRef.current.user
    if (prevAnchor) anchorParams = prevAnchor
  }
  if (!guestParams && smoothedRef.current) {
    const prevGuest = anchorTo === 'pro' ? smoothedRef.current.user : smoothedRef.current.pro
    if (prevGuest) guestParams = prevGuest
  }

  // Anchor skeleton: no transformation, stays at its natural position
  const anchorCoords = anchorLm ? transformLandmarks(anchorLm, canvasWidth, canvasHeight) : []

  // Guest skeleton: translate to anchor's hip center and scale to anchor's torso size
  let guestCoords
  if (guestLm && guestParams && anchorParams) {
    const scale = anchorParams.torsoLength / guestParams.torsoLength
    const guestAligned = guestLm.map(([x, y, z]) => [
      (x - guestParams.hipCenter[0]) * scale + anchorParams.hipCenter[0],
      (y - guestParams.hipCenter[1]) * scale + anchorParams.hipCenter[1],
      z ?? 0,
    ])
    guestCoords = guestAligned.map(([x, y]) => [x * canvasWidth, y * canvasHeight])
  } else {
    guestCoords = guestLm ? transformLandmarks(guestLm, canvasWidth, canvasHeight) : []
  }

  // Map back to user/pro regardless of anchor direction
  const userCoords = anchorTo === 'pro' ? guestCoords : anchorCoords
  const proCoords = anchorTo === 'pro' ? anchorCoords : guestCoords

  return { userCoords, proCoords }
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
 * Detect handedness by comparing total wrist displacement across all frames.
 * The hitting hand moves far more than the non-hitting hand during a swing.
 *
 * @param {number[][][]} landmarks  All frames: [frame][landmark][x,y,z]
 * @returns {'right'|'left'}
 */
export function detectHandedness(landmarks) {
  if (!landmarks || landmarks.length < 2) return 'right'

  let leftDisp = 0
  let rightDisp = 0

  for (let i = 1; i < landmarks.length; i++) {
    const prev = landmarks[i - 1]
    const curr = landmarks[i]
    if (!prev || !curr) continue

    const pl = prev[LEFT_WRIST]
    const cl = curr[LEFT_WRIST]
    if (pl && cl) {
      const dx = cl[0] - pl[0]
      const dy = cl[1] - pl[1]
      leftDisp += Math.sqrt(dx * dx + dy * dy)
    }

    const pr = prev[RIGHT_WRIST]
    const cr = curr[RIGHT_WRIST]
    if (pr && cr) {
      const dx = cr[0] - pr[0]
      const dy = cr[1] - pr[1]
      rightDisp += Math.sqrt(dx * dx + dy * dy)
    }
  }

  return rightDisp >= leftDisp ? 'right' : 'left'
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
