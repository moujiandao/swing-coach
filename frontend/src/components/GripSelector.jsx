import { useState } from 'react'
import { Check } from 'lucide-react'

/**
 * Grip type data with associated pro players.
 * Player image paths follow /players/{slug}.jpg convention.
 */
const GRIPS = [
  {
    value: 'semi_western',
    label: 'Semi-Western',
    image: '/grips/semi-western.jpg',
    players: [
      { name: 'Jannik Sinner', slug: 'jannik-sinner' },
      { name: 'Carlos Alcaraz', slug: 'carlos-alcaraz' },
    ],
  },
  {
    value: 'modified_eastern',
    label: 'Modified Eastern',
    image: '/grips/modified-eastern.jpg',
    players: [
      { name: 'Roger Federer', slug: 'roger-federer' },
    ],
  },
  {
    value: 'eastern',
    label: 'Eastern',
    image: '/grips/eastern.jpg',
    players: [
      { name: 'Roberto Bautista Agut', slug: 'roberto-bautista-agut' },
      { name: 'JJ Wolf', slug: 'jj-wolf' },
    ],
  },
  {
    value: 'western',
    label: 'Western',
    image: '/grips/western.jpg',
    players: [
      { name: 'Kei Nishikori', slug: 'kei-nishikori' },
      { name: 'Taylor Fritz', slug: 'taylor-fritz' },
    ],
  },
]

// Exported so Upload.jsx can use it for filtering pro references
export { GRIPS }

/**
 * Renders a player's headshot with a graceful fallback to initials.
 */
function PlayerHeadshot({ name, slug }) {
  const [imgError, setImgError] = useState(false)

  const initials = name
    .split(' ')
    .map((w) => w[0])
    .join('')
    .slice(0, 2)
    .toUpperCase()

  if (imgError) {
    return (
      <div className="h-8 w-8 rounded-full bg-gray-700 flex items-center justify-center text-[10px] font-bold text-gray-300 shrink-0">
        {initials}
      </div>
    )
  }

  return (
    <img
      src={`/players/${slug}.jpg`}
      alt={name}
      onError={() => setImgError(true)}
      className="h-8 w-8 rounded-full object-cover shrink-0"
    />
  )
}

/**
 * GripSelector - grid of grip image cards with associated player headshots.
 * Used as a sub-selector when "Forehand" stroke type is chosen.
 */
export default function GripSelector({ selectedGrip, onSelect }) {
  return (
    <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
      {GRIPS.map((grip) => {
        const isSelected = selectedGrip === grip.value
        return (
          <button
            key={grip.value}
            type="button"
            onClick={() => onSelect(grip.value)}
            className={`relative rounded-xl border overflow-hidden text-left transition-all duration-200
              ${isSelected
                ? 'border-[#2D8653] ring-2 ring-[#2D8653]/40 bg-[#2D8653]/10'
                : 'border-gray-700 hover:border-gray-500 bg-gray-900'
              }`}
          >
            {/* Grip image */}
            <GripImage src={grip.image} label={grip.label} />

            {/* Label + players */}
            <div className="px-3 py-2.5 space-y-2">
              <p className={`text-sm font-semibold ${isSelected ? 'text-white' : 'text-gray-200'}`}>
                {grip.label}
              </p>
              <div className="flex flex-wrap gap-2">
                {grip.players.map((player) => (
                  <div key={player.slug} className="flex items-center gap-1.5">
                    <PlayerHeadshot name={player.name} slug={player.slug} />
                    <span className="text-xs text-gray-400">{player.name}</span>
                  </div>
                ))}
              </div>
            </div>

            {/* Selected checkmark */}
            {isSelected && (
              <div className="absolute top-2 right-2 flex h-6 w-6 items-center justify-center rounded-full bg-[#2D8653]">
                <Check className="h-3.5 w-3.5 text-white" />
              </div>
            )}
          </button>
        )
      })}
    </div>
  )
}

/**
 * Grip image with graceful fallback for missing assets.
 */
function GripImage({ src, label }) {
  const [imgError, setImgError] = useState(false)

  if (imgError) {
    return (
      <div className="h-24 bg-gray-800 flex items-center justify-center">
        <span className="text-xs text-gray-500">{label}</span>
      </div>
    )
  }

  return (
    <img
      src={src}
      alt={`${label} grip`}
      onError={() => setImgError(true)}
      className="w-full h-24 object-cover"
    />
  )
}
