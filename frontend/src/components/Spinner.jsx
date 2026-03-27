export default function Spinner({ className = 'h-6 w-6' }) {
  return (
    <div className={`relative shrink-0 ${className}`}>
      <div className="absolute inset-0 rounded-full border-2 border-gray-800" />
      <div className="absolute inset-0 rounded-full border-2 border-t-[#2D8653] animate-spin" />
    </div>
  )
}
