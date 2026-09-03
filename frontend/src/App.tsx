import { lazy, Suspense, Component } from 'react'
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import { Spin } from 'antd'
import { AuthProvider, useAuth } from './stores/auth'
import AppLayout from './components/AppLayout'
import Login from './pages/Login'

const Home = lazy(() => import('./pages/Home'))
const Projects = lazy(() => import('./pages/Projects'))
const ProjectDetail = lazy(() => import('./pages/ProjectDetail'))
const Storyboard = lazy(() => import('./pages/Storyboard'))
const Assets = lazy(() => import('./pages/Assets'))
const Video = lazy(() => import('./pages/Video'))
const VideoConcat = lazy(() => import('./pages/VideoConcat'))
const DocumentReader = lazy(() => import('./pages/DocumentReader'))
const Facts = lazy(() => import('./pages/Facts'))
const RenderWorkspace = lazy(() => import('./pages/RenderWorkspace'))
const VoiceWorkspace = lazy(() => import('./pages/VoiceWorkspace'))
const VoiceTemplates = lazy(() => import('./pages/VoiceTemplates'))
const AiVideo = lazy(() => import('./pages/AiVideo'))
const VideoTemplateCreator = lazy(() => import('./pages/VideoTemplateCreator'))
const ConstructionWorkbenchPage = lazy(() => import('./pages/ConstructionWorkbenchPage'))
const AccountSettings = lazy(() => import('./pages/AccountSettings'))
const Collaboration = lazy(() => import('./pages/Collaboration'))
const AcceptInvite = lazy(() => import('./pages/AcceptInvite'))

function PageFallback() {
  return (
    <div style={{ display: 'flex', justifyContent: 'center', alignItems: 'center', minHeight: '50vh' }}>
      <Spin size="large" />
    </div>
  )
}

class ErrorBoundary extends Component<React.PropsWithChildren, { hasError: boolean }> {
  state = { hasError: false }

  static getDerivedStateFromError() {
    return { hasError: true }
  }

  render() {
    if (this.state.hasError) {
      return (
        <div style={{ padding: 48, textAlign: 'center' }}>
          页面加载失败，请刷新后重试。
          <br />
          <button type="button" onClick={() => window.location.reload()}>刷新页面</button>
        </div>
      )
    }
    return this.props.children
  }
}

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
    <ErrorBoundary>
      <AuthProvider>
        <BrowserRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
          <Suspense fallback={<PageFallback />}>
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
            <Route path="/account-settings" element={<AccountSettings />} />
            <Route path="/project/:projectId" element={<ProjectDetail />} />
            <Route path="/project/:projectId/reader" element={<DocumentReader />} />
            <Route path="/project/:projectId/facts" element={<Facts />} />
            <Route path="/project/:projectId/render" element={<RenderWorkspace />} />
            <Route path="/project/:projectId/voice" element={<VoiceWorkspace />} />
            <Route path="/project/:projectId/voice-templates" element={<VoiceTemplates />} />
            <Route path="/project/:projectId/storyboard" element={<Storyboard />} />
            <Route path="/project/:projectId/assets" element={<Assets />} />
            <Route path="/project/:projectId/ai-video" element={<AiVideo />} />
            <Route path="/project/:projectId/ai-video/advanced" element={<ConstructionWorkbenchPage />} />
            <Route path="/project/:projectId/ai-video/templates/new" element={<VideoTemplateCreator />} />
            <Route path="/project/:projectId/video" element={<Video />} />
            <Route path="/project/:projectId/video-concat" element={<VideoConcat />} />
            <Route path="/project/:projectId/collaboration" element={<Collaboration />} />
            <Route path="/invite/accept" element={<AcceptInvite />} />
          </Route>
          <Route path="*" element={<Navigate to="/" replace />} />
            </Routes>
          </Suspense>
        </BrowserRouter>
      </AuthProvider>
    </ErrorBoundary>
  )
}
