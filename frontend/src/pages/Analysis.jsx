import { useParams } from 'react-router-dom'

export default function Analysis() {
  const { id } = useParams()

  return (
    <div>
      <h1 className="text-2xl font-bold mb-2">Analysis Results</h1>
      <p className="text-gray-400">Analysis ID: <code className="text-[#2D8653]">{id}</code></p>
    </div>
  )
}
