import { Component } from 'react'
import { Link } from 'react-router-dom'

export default class ErrorBoundary extends Component {
  constructor(props) {
    super(props)
    this.state = { hasError: false, message: null }
  }

  static getDerivedStateFromError(error) {
    return { hasError: true, message: error?.message ?? 'Unknown error' }
  }

  componentDidCatch(error, info) {
    console.error('ErrorBoundary caught:', error, info)
  }

  render() {
    if (!this.state.hasError) return this.props.children

    return (
      <div className="flex flex-col items-center justify-center py-24 text-center space-y-4">
        <h2 className="text-xl font-semibold text-white">Something went wrong</h2>
        <p className="text-sm text-gray-400 max-w-sm">{this.state.message}</p>
        <Link
          to="/"
          onClick={() => this.setState({ hasError: false, message: null })}
          className="inline-block rounded-xl bg-[#2D8653] px-6 py-2.5 text-sm font-semibold text-white hover:bg-[#236b42] transition-colors"
        >
          Go Home
        </Link>
      </div>
    )
  }
}
