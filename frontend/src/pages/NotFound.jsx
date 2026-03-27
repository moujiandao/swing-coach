import { Link } from 'react-router-dom'

export default function NotFound() {
  return (
    <div className="flex flex-col items-center justify-center py-24 text-center space-y-4">
      <span className="text-6xl font-bold text-gray-800">404</span>
      <h2 className="text-xl font-semibold text-white">Page Not Found</h2>
      <p className="text-sm text-gray-400">That URL doesn&apos;t exist.</p>
      <Link
        to="/"
        className="inline-block rounded-xl bg-[#2D8653] px-6 py-2.5 text-sm font-semibold text-white hover:bg-[#236b42] transition-colors"
      >
        Go Home
      </Link>
    </div>
  )
}
