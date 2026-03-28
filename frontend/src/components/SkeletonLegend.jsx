/**
 * SkeletonLegend
 *
 * Compact legend bar explaining the DualSkeletonCanvas color coding.
 */
export default function SkeletonLegend({ className = '' }) {
  return (
    <div className={`flex items-center gap-5 text-xs text-gray-300 ${className}`}>
      {/* User skeleton */}
      <div className="flex items-center gap-2">
        <svg width="28" height="10" aria-hidden>
          <line x1="0" y1="5" x2="28" y2="5" stroke="#00D4FF" strokeWidth="2.5" strokeLinecap="round" />
          <circle cx="14" cy="5" r="3" fill="#00D4FF" />
        </svg>
        <span>Your swing</span>
      </div>

      {/* Pro skeleton */}
      <div className="flex items-center gap-2">
        <svg width="28" height="10" aria-hidden>
          <line
            x1="0" y1="5" x2="28" y2="5"
            stroke="#FFD700" strokeWidth="2.5" strokeLinecap="round"
            strokeDasharray="6 3"
          />
          <circle cx="14" cy="5" r="3" fill="#FFD700" />
        </svg>
        <span>Pro reference</span>
      </div>

      {/* Deviation highlight */}
      <div className="flex items-center gap-2">
        <svg width="20" height="20" aria-hidden>
          <circle cx="10" cy="10" r="7" fill="none" stroke="#EF4444" strokeWidth="2" opacity="0.85" />
          <circle cx="10" cy="10" r="3" fill="#EF4444" opacity="0.5" />
        </svg>
        <span>Deviation area</span>
      </div>
    </div>
  )
}
