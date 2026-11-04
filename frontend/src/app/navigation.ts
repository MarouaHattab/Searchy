import { Film, LayoutDashboard, MessageSquare, Search, Settings, Users, Workflow } from 'lucide-react'

export const navigation = [
  { label: 'Dashboard', to: '/', icon: LayoutDashboard, group: 'Workspace' },
  { label: 'AI Search', to: '/search', icon: Search, group: 'Workspace' },
  { label: 'Ask Chat', to: '/chat', icon: MessageSquare, group: 'Workspace' },
  { label: 'Video Library', to: '/library', icon: Film, group: 'Workspace' },
  { label: 'Characters', to: '/characters', icon: Users, group: 'Workspace' },
  { label: 'Processing Jobs', to: '/jobs', icon: Workflow, group: 'Management' },
  { label: 'Settings', to: '/settings', icon: Settings, group: 'Management' },
]
