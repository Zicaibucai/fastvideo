export const RECENT_PROJECTS_KEY = 'fastvideo_recent_project_ids'
export const PROJECT_ACTIVITY_KEY = 'fastvideo_project_activity_days'

type ProjectLike = {
  id: string
}

type RecentProjectVisit = {
  id: string
  openedAt: number
}

type ProjectActivityDays = Record<string, string[]>

function readVisits(): RecentProjectVisit[] {
  if (typeof window === 'undefined') return []
  try {
    const raw = window.localStorage.getItem(RECENT_PROJECTS_KEY)
    const visits = raw ? JSON.parse(raw) : []
    return Array.isArray(visits) ? visits : []
  } catch {
    return []
  }
}

function localDateKey(date = new Date()): string {
  const year = date.getFullYear()
  const month = String(date.getMonth() + 1).padStart(2, '0')
  const day = String(date.getDate()).padStart(2, '0')
  return `${year}-${month}-${day}`
}

function readActivityDays(): ProjectActivityDays {
  if (typeof window === 'undefined') return {}
  try {
    const raw = window.localStorage.getItem(PROJECT_ACTIVITY_KEY)
    const activity = raw ? JSON.parse(raw) : {}
    return activity && typeof activity === 'object' ? activity : {}
  } catch {
    return {}
  }
}

export function rememberProjectOpened(projectId: string) {
  if (typeof window === 'undefined' || !projectId) return
  const visits = readVisits().filter((visit) => visit.id !== projectId)
  visits.unshift({ id: projectId, openedAt: Date.now() })
  try {
    window.localStorage.setItem(RECENT_PROJECTS_KEY, JSON.stringify(visits.slice(0, 50)))

    const activity = readActivityDays()
    const today = localDateKey()
    const days = Array.isArray(activity[projectId]) ? activity[projectId] : []
    if (!days.includes(today)) {
      activity[projectId] = [...days, today].slice(-365)
      window.localStorage.setItem(PROJECT_ACTIVITY_KEY, JSON.stringify(activity))
    }
  } catch {
    // 隐私模式或存储空间不足时，不影响项目页面正常使用。
  }
}

export function getProjectActiveDays(projectId: string): number {
  const days = readActivityDays()[projectId]
  return Array.isArray(days) ? days.length : 0
}

export function getProjectActivityDays(projectId: string): string[] {
  const days = readActivityDays()[projectId]
  return Array.isArray(days) ? days : []
}

export function getRecentlyOpenedProjects<T extends ProjectLike>(projects: T[]): T[] {
  const visits = readVisits()
  const projectsById = new Map(projects.map((project) => [project.id, project]))
  return visits
    .map((visit) => projectsById.get(visit.id))
    .filter((project): project is T => Boolean(project))
}
