import { BrowserRouter, Routes, Route, NavLink } from 'react-router-dom'
import Upload from './pages/Upload'
import Analysis from './pages/Analysis'
import History from './pages/History'

function NavBar() {
  const linkClass = ({ isActive }) =>
    `px-3 py-1 rounded text-sm font-medium transition-colors ${
      isActive
        ? 'text-white bg-[#2D8653]'
        : 'text-gray-400 hover:text-white'
    }`

  return (
    <header className="bg-gray-900 border-b border-gray-800">
      <div className="max-w-4xl mx-auto px-4 h-14 flex items-center justify-between">
        <span className="text-white font-bold text-lg tracking-tight">
          Swing<span className="text-[#2D8653]">Coach</span>
        </span>
        <nav className="flex gap-2">
          <NavLink to="/" end className={linkClass}>Upload</NavLink>
          <NavLink to="/history" className={linkClass}>History</NavLink>
        </nav>
      </div>
    </header>
  )
}

export default function App() {
  return (
    <BrowserRouter>
      <div className="min-h-screen bg-gray-950 text-gray-100">
        <NavBar />
        <main className="max-w-4xl mx-auto px-4 py-8">
          <Routes>
            <Route path="/" element={<Upload />} />
            <Route path="/analysis/:id" element={<Analysis />} />
            <Route path="/history" element={<History />} />
          </Routes>
        </main>
      </div>
    </BrowserRouter>
  )
}
