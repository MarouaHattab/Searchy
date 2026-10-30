import { lazy } from 'react'
import { ChevronLeft, Search } from 'lucide-react'
import { Link, Route, Routes } from 'react-router'
import { Shell } from './Shell'

const DashboardPage = lazy(() => import('../pages/DashboardPage'))
const SearchPage = lazy(() => import('../features/search/SearchPage'))
const LibraryPage = lazy(() => import('../pages/LibraryPage'))
const VideoPage = lazy(() => import('../pages/VideoPage'))
const ScenePage = lazy(() => import('../features/player/ScenePage'))
const CharactersPage = lazy(() => import('../pages/CharactersPage'))
const JobsPage = lazy(() => import('../pages/JobsPage'))
const SettingsPage = lazy(() => import('../pages/SettingsPage'))

function NotFound() {
  return (
    <div className="state-panel">
      <Search size={32} />
      <h1>This page isn’t in the collection.</h1>
      <p>Return to your workspace and find your next moment.</p>
      <Link className="button button-primary" to="/">
        <ChevronLeft size={15} />
        Back to dashboard
      </Link>
    </div>
  )
}

export default function App() {
  return (
    <Routes>
      <Route element={<Shell />}>
        <Route index element={<DashboardPage />} />
        <Route path="search" element={<SearchPage />} />
        <Route path="library" element={<LibraryPage />} />
        <Route path="library/:id" element={<VideoPage />} />
        <Route path="scenes/:id" element={<ScenePage />} />
        <Route path="characters" element={<CharactersPage />} />
        <Route path="jobs" element={<JobsPage />} />
        <Route path="settings" element={<SettingsPage />} />
        <Route path="*" element={<NotFound />} />
      </Route>
    </Routes>
  )
}
