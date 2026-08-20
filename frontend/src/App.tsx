import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import { Spin } from 'antd'
import { AuthProvider, useAuth } from './stores/auth'
import AppLayout from './components/AppLayout'
import Login from './pages/Login'
import Home from './pages/Home'
import Projects from './pages/Projects'
import ProjectDetail from './pages/ProjectDetail'
import Storyboard from './pages/Storyboard'
import Assets from './pages/Assets'
import Video from './pages/Video'
import DocumentReader from './pages/DocumentReader'
import Facts from './pages/Facts'
import RenderWorkspace from './pages/RenderWorkspace'
import VoiceWorkspace from './pages/VoiceWorkspace'
import VoiceTemplates from './pages/VoiceTemplates'
import AiVideo from './pages/AiVideo'

function RequireAuth({ children }: { children: React.ReactElement }) {
  const { user, loading } = useAuth()
  if (loading) {
    return (
      <div style={{ display: 'flex', justifyContent: 'center', alignItems: 'center', height: '100vh' }}>
        <Spin size="large" />
      </div>
    )
  }
  if (!user) return <Navigate to="/login" replace />
  return children
}

export default function App() {
  return (
    <AuthProvider>
      <BrowserRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
        <Routes>
          <Route path="/login" element={<Login />} />
          <Route
            element={
              <RequireAuth>
                <AppLayout />
              </RequireAuth>
            }
          >
            <Route path="/" element={<Home />} />
            <Route path="/projects" element={<Projects />} />
            <Route path="/project/:projectId" element={<ProjectDetail />} />
            <Route path="/project/:projectId/reader" element={<DocumentReader />} />
            <Route path="/project/:projectId/facts" element={<Facts />} />
            <Route path="/project/:projectId/render" element={<RenderWorkspace />} />
            <Route path="/project/:projectId/voice" element={<VoiceWorkspace />} />
            <Route path="/project/:projectId/voice-templates" element={<VoiceTemplates />} />
            <Route path="/project/:projectId/storyboard" element={<Storyboard />} />
            <Route path="/project/:projectId/assets" element={<Assets />} />
            <Route path="/project/:projectId/ai-video" element={<AiVideo />} />
            <Route path="/project/:projectId/video" element={<Video />} />
          </Route>
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </BrowserRouter>
    </AuthProvider>
  )
}
