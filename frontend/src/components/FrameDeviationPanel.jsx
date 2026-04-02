/**
 * FrameDeviationPanel
 *
 * Collapsible panel showing real-time deviation data for the current frame.
 * Updates live as the user scrubs through frames. Joints are grouped by body region.
 */

// Body region grouping — order determines display order
const BODY_REGIONS = [
  { label: 'Hitting Arm',      joints: ['elbow_angle', 'racket_arm_elevation'] },
  { label: 'Non-Hitting Arm',  joints: ['left_elbow_angle', 'left_arm_elevation'] },
  { label: 'Torso',            joints: ['shoulder_rotation', 'hip_rotation', 'trunk_rotation'] },
  { label: 'Legs & Stance',    joints: ['knee_bend', 'stance_width'] },
  { label: 'Head',             joints: ['head_movement'] },
]

const SEVERITY_STYLE = {
  critical: { bg: '#7f1d1d', text: '#ef4444' },
  moderate: { bg: '#78350f', text: '#f59e0b' },
  minor:    { bg: '#1e3a5f', text: '#3b82f6' },
}

function AngleDisplay({ userAngle, proAngle, diffDegrees }) {
  if (userAngle == null || proAngle == null) return null
  return (
    <div className="flex items-center gap-2 text-xs font-mono">
      <span className="text-[#00D4FF]">{Math.round(userAngle)}°</span>
      <span className="text-gray-600">you</span>
      <span className="text-gray-600 mx-0.5">vs</span>
      <span className="text-[#FFD700]">{Math.round(proAngle)}°</span>
      <span className="text-gray-600">pro</span>
      {diffDegrees != null && (
        <span className="text-gray-500 ml-1">({Math.round(Math.abs(diffDegrees))}° diff)</span>
      )}
    </div>
  )
}

function JointRow({ jointDev, severity }) {
  const colors = SEVERITY_STYLE[severity] || SEVERITY_STYLE.moderate
  const jointLabel = jointDev.joint_name
    ?.replace(/_/g, ' ')
    .replace(/\b\w/g, (c) => c.toUpperCase()) ?? 'Joint'
  const directionLabel = jointDev.direction?.replace(/_/g, ' ') ?? ''

  return (
    <div className="rounded-lg border border-gray-800 bg-gray-950 p-3 space-y-1.5">
      <div className="flex items-center justify-between gap-2">
        <span className="text-sm font-medium text-gray-200">{jointLabel}</span>
        <span
          className="text-[10px] font-semibold px-2 py-0.5 rounded"
          style={{ background: colors.bg, color: colors.text }}
        >
          {severity}
        </span>
      </div>
      <AngleDisplay
        userAngle={jointDev.user_angle}
        proAngle={jointDev.pro_angle}
        diffDegrees={jointDev.diff_degrees}
      />
      {directionLabel && jointDev.diff_degrees != null && (
        <p className="text-xs text-gray-400">
          {Math.round(Math.abs(jointDev.diff_degrees))}° {directionLabel}
        </p>
      )}
    </div>
  )
}

export default function FrameDeviationPanel({ frameDeviations, currentFrame, isOpen, onToggle }) {
  const frameDevs = (frameDeviations ?? []).filter((d) => d.frame_index === currentFrame)

  // Build a flat lookup: joint_name → { jointDev, severity }
  const activeJoints = {}
  for (const fd of frameDevs) {
    for (const jd of fd.deviating_joints ?? []) {
      activeJoints[jd.joint_name] = { jointDev: jd, severity: fd.severity }
    }
  }

  const totalDeviations = Object.keys(activeJoints).length

  return (
    <div className="rounded-xl border border-gray-800 bg-gray-900">
      {/* Header / toggle */}
      <button
        className="w-full flex items-center justify-between px-4 py-3 text-xs font-semibold
                   uppercase tracking-widest text-gray-400 hover:text-gray-200 transition-colors
                   focus:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-[#2D8653]"
        onClick={onToggle}
        aria-expanded={isOpen}
      >
        <span>
          Frame Analysis
          {totalDeviations > 0 && (
            <span className="ml-2 text-[10px] font-bold text-red-400">
              {totalDeviations} deviation{totalDeviations !== 1 ? 's' : ''}
            </span>
          )}
        </span>
        <span className="text-gray-600">{isOpen ? '▲' : '▼'}</span>
      </button>

      {isOpen && (
        <div className="px-4 pb-4 space-y-3">
          {totalDeviations === 0 ? (
            <div className="flex items-center gap-2 text-sm text-green-400 py-1">
              <span className="text-base">✓</span>
              <span>No deviations on this frame.</span>
            </div>
          ) : (
            BODY_REGIONS.map(({ label, joints }) => {
              const regionJoints = joints.filter((j) => activeJoints[j])
              if (regionJoints.length === 0) return null
              return (
                <div key={label}>
                  <p className="text-[10px] font-semibold uppercase tracking-widest text-gray-600 mb-1.5">
                    {label}
                  </p>
                  <div className="space-y-2">
                    {regionJoints.map((jointKey) => {
                      const { jointDev, severity } = activeJoints[jointKey]
                      return <JointRow key={jointKey} jointDev={jointDev} severity={severity} />
                    })}
                  </div>
                </div>
              )
            })
          )}
        </div>
      )}
    </div>
  )
}
