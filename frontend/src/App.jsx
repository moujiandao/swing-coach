import { BrowserRouter, Routes, Route, NavLink, Link } from 'react-router-dom'
import Upload from './pages/Upload'
import Analysis from './pages/Analysis'
import History from './pages/History'
import NotFound from './pages/NotFound'
import ErrorBoundary from './components/ErrorBoundary'

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
        <Link to="/" className="text-white font-bold text-lg tracking-tight hover:opacity-80 transition-opacity">
          Swing<span className="text-[#2D8653]">Coach</span>
        </Link>
        <nav className="flex gap-2">
          <NavLink to="/" end className={linkClass}>Upload</NavLink>
          <NavLink to="/history" className={linkClass}>History</NavLink>
        </nav>
      </div>
    </header>
  )
}

function Footer() {
  return (
    <footer className="border-t border-gray-800 mt-16">
      <div className="max-w-4xl mx-auto px-4 py-6 text-center text-xs text-gray-600">
        Built by Brian &bull; Powered by MediaPipe + Claude
      </div>
    </footer>
  )
}

export default function App() {
  return (
    <BrowserRouter>
      <div className="min-h-screen bg-gray-950 text-gray-100 flex flex-col">
        <NavBar />
        <main className="flex-1 max-w-4xl w-full mx-auto px-4 py-8">
          <ErrorBoundary>
            <Routes>
              <Route path="/" element={<Upload />} />
              <Route path="/analysis/:id" element={<Analysis />} />
              <Route path="/history" element={<History />} />
              <Route path="*" element={<NotFound />} />
            </Routes>
          </ErrorBoundary>
        </main>
        <Footer />
      </div>
    </BrowserRouter>
  )
}
