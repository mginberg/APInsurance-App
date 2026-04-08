import { useState, useEffect, useCallback, useRef } from 'react'
import { BrowserRouter, Routes, Route, useParams, useNavigate } from 'react-router-dom'
import {
  Trophy, Medal, Star, Flame, Crown, Zap, RefreshCw, DollarSign,
  LogIn, LogOut, X, Shield, LayoutDashboard, Clock, TrendingUp,
  CheckCircle, Users, FileText, UserPlus, Search, Trash2,
  Settings, Save, RotateCw, Upload, AlertCircle, AlertTriangle, UserX, UserCheck, Key, Menu,
  Sun, Moon, MapPin, Briefcase, BarChart3, Download, ChevronRight, ChevronDown, PanelRightClose,
  Calendar, XCircle,
} from 'lucide-react'
import { AuthProvider, useAuth } from './AuthContext'
import DealSubmission from './DealSubmission'

const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:8001'

interface LeaderboardEntry { name: string; deals: number; premium: number }
interface LeaderboardData { leaders: LeaderboardEntry[]; period: string; start_date: string; end_date: string; total_deals: number; total_premium: number }
interface DealBreakdownItem { label: string; count: number; premium: number }
interface DealBreakdown { states: DealBreakdownItem[]; plan_types: DealBreakdownItem[] }
interface LeaderboardResponse { daily: LeaderboardData; weekly: LeaderboardData; monthly: LeaderboardData; last_sync: string; agency_name?: string; agency_slug?: string; daily_breakdown?: DealBreakdown; weekly_breakdown?: DealBreakdown; monthly_breakdown?: DealBreakdown }

const getAvatarColor = (name: string): string => {
  const colors = ['from-violet-500 to-purple-600','from-teal-500 to-cyan-600','from-rose-500 to-pink-600','from-amber-500 to-orange-600','from-emerald-500 to-green-600','from-fuchsia-500 to-purple-600','from-sky-500 to-blue-600','from-indigo-500 to-violet-600','from-lime-500 to-green-600','from-red-500 to-rose-600']
  let hash = 0
  for (let i = 0; i < name.length; i++) { hash = name.charCodeAt(i) + ((hash << 5) - hash) }
  return colors[Math.abs(hash) % colors.length]
}

const getInitials = (name: string): string => {
  const parts = name.split(' ')
  if (parts.length >= 2) return (parts[0][0] + parts[parts.length - 1][0]).toUpperCase()
  return name.slice(0, 2).toUpperCase()
}

const getRankIcon = (rank: number) => {
  if (rank === 1) return <Crown className="w-6 h-6 text-yellow-400 drop-shadow-lg" />
  if (rank === 2) return <Medal className="w-5 h-5 text-gray-300" />
  if (rank === 3) return <Medal className="w-5 h-5 text-amber-600" />
  return null
}

const getRankBadge = (rank: number) => {
  if (rank === 1) return 'bg-gradient-to-r from-yellow-400 to-yellow-500 text-black font-bold shadow-lg shadow-yellow-400/30'
  if (rank === 2) return 'bg-gradient-to-r from-gray-300 to-gray-400 text-gray-800 font-bold'
  if (rank === 3) return 'bg-gradient-to-r from-amber-500 to-amber-600 text-white font-bold'
  return 'bg-slate-200 text-slate-600'
}

const getStreakEmoji = (deals: number) => {
  if (deals >= 10) return <Flame className="w-5 h-5 text-orange-500 animate-pulse" />
  if (deals >= 5) return <Zap className="w-4 h-4 text-yellow-400" />
  if (deals >= 3) return <Star className="w-4 h-4 text-purple-600" />
  return null
}

const formatCurrency = (amount: number): string => new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD', minimumFractionDigits: 0, maximumFractionDigits: 0 }).format(amount)

const fmtDate = (v: string | null | undefined): string => {
  if (!v) return '—'
  const [y, m, d] = v.split('-')
  if (!y || !m || !d) return v
  return `${parseInt(m)}/${parseInt(d)}/${y}`
}


function LoginModal({ onClose, role }: { onClose: () => void; role: 'agent' | 'admin' }) {
  const { login } = useAuth()
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)
  const navigate = useNavigate()
  const isAdmin = role === 'admin'

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setLoading(true)
    setError('')
    const result = await login(username, password)
    setLoading(false)
    if (result.success) { onClose(); navigate('/portal') } else { setError(result.error || 'Login failed') }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm">
      <div className="bg-white border border-slate-200 rounded-2xl p-8 w-full max-w-md shadow-2xl relative">
        <button onClick={onClose} className="absolute top-4 right-4 text-slate-400 hover:text-slate-700"><X className="w-5 h-5" /></button>
        <div className="text-center mb-6">
          {isAdmin ? <Shield className="w-12 h-12 text-purple-600 mx-auto mb-3" /> : <LogIn className="w-12 h-12 text-blue-600 mx-auto mb-3" />}
          <h2 className="text-2xl font-bold text-slate-800">{isAdmin ? 'Admin Sign In' : 'Agent Sign In'}</h2>
          <p className="text-slate-500 text-sm mt-1">{isAdmin ? 'Access the agency management portal' : 'View your deals and performance'}</p>
        </div>
        <form onSubmit={handleSubmit} className="space-y-4">
          {error && <div className="bg-red-500/10 border border-red-500/30 rounded-lg p-3 text-red-600 text-sm text-center">{error}</div>}
          <div>
            <label className="block text-sm font-medium text-slate-600 mb-1">Username</label>
            <input type="text" value={username} onChange={e => setUsername(e.target.value)} className="w-full px-4 py-3 bg-white border border-slate-300 rounded-lg text-slate-800 placeholder-slate-400 focus:border-blue-500 focus:ring-1 focus:ring-blue-500 outline-none transition" placeholder={isAdmin ? 'admin@agency.com' : 'jsmith'} required />
          </div>
          <div>
            <label className="block text-sm font-medium text-slate-600 mb-1">Password</label>
            <input type="password" value={password} onChange={e => setPassword(e.target.value)} className="w-full px-4 py-3 bg-white border border-slate-300 rounded-lg text-slate-800 placeholder-slate-400 focus:border-blue-500 focus:ring-1 focus:ring-blue-500 outline-none transition" placeholder="Enter your password" required />
          </div>
          <button type="submit" disabled={loading} className={`w-full py-3 text-white font-semibold rounded-lg transition-all disabled:opacity-50 ${isAdmin ? 'bg-blue-600 hover:bg-blue-700' : 'bg-blue-600 hover:bg-blue-700'}`}>{loading ? 'Signing in...' : 'Sign In'}</button>
        </form>
      </div>
    </div>
  )
}

function ChangePasswordModal() {
  const { token, clearMustChangePassword } = useAuth()
  const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:8001'
  const [currentPassword, setCurrentPassword] = useState('')
  const [newPassword, setNewPassword] = useState('')
  const [confirmPassword, setConfirmPassword] = useState('')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setError('')
    if (newPassword.length < 6) { setError('New password must be at least 6 characters'); return }
    if (newPassword !== confirmPassword) { setError('Passwords do not match'); return }
    setLoading(true)
    try {
      const res = await fetch(`${API_URL}/api/auth/change-password`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
        body: JSON.stringify({ current_password: currentPassword, new_password: newPassword }),
      })
      if (!res.ok) {
        const err = await res.json()
        setError(err.detail || 'Failed to change password')
      } else {
        clearMustChangePassword()
      }
    } catch {
      setError('Network error')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="fixed inset-0 z-[60] flex items-center justify-center bg-black/60 backdrop-blur-sm">
      <div className="bg-white border border-slate-200 rounded-2xl p-8 w-full max-w-md shadow-2xl">
        <div className="text-center mb-6">
          <div className="w-12 h-12 bg-amber-100 rounded-full flex items-center justify-center mx-auto mb-3">
            <Key className="w-6 h-6 text-amber-600" />
          </div>
          <h2 className="text-2xl font-bold text-slate-800">Set Your Password</h2>
          <p className="text-slate-500 text-sm mt-1">You must change your password before continuing</p>
        </div>
        <form onSubmit={handleSubmit} className="space-y-4">
          {error && <div className="bg-red-500/10 border border-red-500/30 rounded-lg p-3 text-red-600 text-sm text-center">{error}</div>}
          <div>
            <label className="block text-sm font-medium text-slate-600 mb-1">Current Password</label>
            <input type="password" value={currentPassword} onChange={e => setCurrentPassword(e.target.value)} className="w-full px-4 py-3 bg-white border border-slate-300 rounded-lg text-slate-800 placeholder-slate-400 focus:border-blue-500 focus:ring-1 focus:ring-blue-500 outline-none transition" placeholder="Enter current password" required />
          </div>
          <div>
            <label className="block text-sm font-medium text-slate-600 mb-1">New Password</label>
            <input type="password" value={newPassword} onChange={e => setNewPassword(e.target.value)} className="w-full px-4 py-3 bg-white border border-slate-300 rounded-lg text-slate-800 placeholder-slate-400 focus:border-blue-500 focus:ring-1 focus:ring-blue-500 outline-none transition" placeholder="At least 6 characters" required />
          </div>
          <div>
            <label className="block text-sm font-medium text-slate-600 mb-1">Confirm New Password</label>
            <input type="password" value={confirmPassword} onChange={e => setConfirmPassword(e.target.value)} className="w-full px-4 py-3 bg-white border border-slate-300 rounded-lg text-slate-800 placeholder-slate-400 focus:border-blue-500 focus:ring-1 focus:ring-blue-500 outline-none transition" placeholder="Re-enter new password" required />
          </div>
          <button type="submit" disabled={loading} className="w-full py-3 bg-blue-600 hover:bg-blue-700 text-white font-semibold rounded-lg transition-all disabled:opacity-50">{loading ? 'Changing...' : 'Set New Password'}</button>
        </form>
      </div>
    </div>
  )
}

interface DealsSummary{ total: { deals: number; premium: number }; today: { deals: number; premium: number }; week: { deals: number; premium: number }; month: { deals: number; premium: number }; agent_name: string; agency_name: string }
interface AgentInfo { id: string; email: string; agent_name: string; is_active: boolean; has_login?: boolean }
interface GhlAgent { agent_name: string; deal_count: number; has_login: boolean }
interface DashboardStats { total_deals: number; total_premium: number; active_count: number; active_premium: number; pending_count: number; pending_premium: number; future_active_count: number; future_active_premium: number; cancelled_count: number; cancelled_premium: number; not_effectuated_count: number; not_effectuated_premium: number; effectuation_rate: number; cancel_rate: number; not_effectuated_rate: number; pending_rate: number; today: { deals: number; premium: number }; week: { deals: number; premium: number }; month: { deals: number; premium: number } }

interface BillableHours { agent_name: string; week_start: string; week_end: string; billable_hours: number; available_hours: number; on_call_hours: number; post_call_billable_hours: number; hourly_rate: number; hourly_pay: number; error?: string }
interface HourlyReportAgent { agent_name: string; matched: boolean; billable_hours: number; available_hours: number; on_call_hours: number; post_call_billable_hours: number }
interface HourlyReport { week_start: string; week_end: string; agents: HourlyReportAgent[]; total_billable_hours: number }
interface BonusWeek { week_start: string; week_end: string; label: string }
interface AgentDeal { id: string; contact_name: string; agent_name: string; premium: number; date_added: string | null; policy_number: string; effective_date: string | null; premium_draft_date: string | null; plan_name: string; status: string; payable: boolean; reason: string }
interface BonusWeekDeals { week_start: string; week_end: string; submitted_deals: AgentDeal[]; submitted_count: number; submitted_premium: number; payable_deals: AgentDeal[]; payable_count: number; payable_premium: number; failed_deals: AgentDeal[]; failed_count: number; failed_premium: number; all_deals_count: number }

interface AuditContact { contact_id: string; name: string; policy_number: string; commission_fields: Record<string, string> }
interface AuditResult { total_contacts: number; contacts_with_commission: number; flagged: AuditContact[] }

type AdminTab = 'dashboard' | 'commission' | 'agents' | 'hourly' | 'submission_agents' | 'audit' | 'settings'
type AgentTab = 'dashboard' | 'deals'

function Portal() {
  const { user, token, logout, agency, mustChangePassword } = useAuth()
  const navigate = useNavigate()
  const isAdmin = user?.role === 'super_admin' || user?.role === 'agency_admin'
  const [adminTab, setAdminTab] = useState<AdminTab>('dashboard')
  const [agentTab, setAgentTab] = useState<AgentTab>('dashboard')
  const [sidebarOpen, setSidebarOpen] = useState(true)

  // Data states
  const [dealsSummary, setDealsSummary] = useState<DealsSummary | null>(null)
  const [agents, setAgents] = useState<AgentInfo[]>([])
  const [dashboardStats, setDashboardStats] = useState<DashboardStats | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [success, setSuccess] = useState('')

  // CSV upload
  const [csvFiles, setCsvFiles] = useState<File[]>([])
  const [uploadResults, setUploadResults] = useState<Record<string, unknown>[] | null>(null)
  const [dragOver, setDragOver] = useState(false)
  const fileInputRef = useRef<HTMLInputElement>(null)

  // Agent management
  const [resetPasswordEmail, setResetPasswordEmail] = useState('')
  const [newPassword, setNewPassword] = useState('')
  const [generatedCredentials, setGeneratedCredentials] = useState<{ email: string; password: string; agent_name: string } | null>(null)
  const [ghlAgents, setGhlAgents] = useState<GhlAgent[]>([])

  // Settings
  const [settingsData, setSettingsData] = useState({ ghl_api_key: '', ghl_location_id: '', ghl_agent_field_id: '', ghl_premium_field_id: '', ghl_advance_status_field_id: '', ghl_paid_to_agent_field_id: '', calltools_api_key: '', calltools_team_id: '' })

  // Bonus week state
  const [bonusWeeks, setBonusWeeks] = useState<BonusWeek[]>([])
  const [selectedWeek, setSelectedWeek] = useState<string>('')
  const [weekDeals, setWeekDeals] = useState<BonusWeekDeals | null>(null)
  const [weekLoading, setWeekLoading] = useState(false)
  const [bonusWeeksLoading, setBonusWeeksLoading] = useState(false)
  const [billableHours, setBillableHours] = useState<BillableHours | null>(null)

  // Hourly report (admin)
  const [hourlyReport, setHourlyReport] = useState<HourlyReport | null>(null)
  const [hourlyWeeks, setHourlyWeeks] = useState<BonusWeek[]>([])
  const [hourlySelectedWeek, setHourlySelectedWeek] = useState<string>('')
  const [hourlyLoading, setHourlyLoading] = useState(false)

  // Commission Audit
  const [auditResult, setAuditResult] = useState<AuditResult | null>(null)
  const [auditLoading, setAuditLoading] = useState(false)
  const [auditClearing, setAuditClearing] = useState(false)
  const [auditSelected, setAuditSelected] = useState<Set<string>>(new Set())
  const [auditSearch, setAuditSearch] = useState('')

  // Admin viewing agent
  const [viewingAgentName, setViewingAgentName] = useState<string | null>(null)
  const [inactiveCollapsed, setInactiveCollapsed] = useState(true)

  const headers: Record<string, string> = { Authorization: 'Bearer ' + (token || ''), 'Content-Type': 'application/json' }

  const agencySlug = agency?.slug || 'ap-insurance'

  // Submission agents state
  const [submissionAgents, setSubmissionAgents] = useState<{id: string; name: string; created_at: string}[]>([])
  const [submissionAgentInput, setSubmissionAgentInput] = useState('')
  const [submissionAgentLoading, setSubmissionAgentLoading] = useState(false)

  const fetchSubmissionAgents = useCallback(async () => {
    if (!isAdmin) return
    try {
      const res = await fetch(API_URL + '/api/submission-agents/' + agencySlug + '/admin', { headers })
      if (res.ok) { const data = await res.json(); setSubmissionAgents(data.agents || []) }
    } catch { /* ignore */ }
  }, [token, agencySlug, isAdmin])

  const handleAddSubmissionAgents = async () => {
    const names = submissionAgentInput.split('\n').map(n => n.trim()).filter(Boolean)
    if (names.length === 0) return
    setSubmissionAgentLoading(true)
    try {
      const res = await fetch(API_URL + '/api/submission-agents/' + agencySlug, { method: 'POST', headers, body: JSON.stringify({ names }) })
      if (res.ok) { const data = await res.json(); setSuccess(`Added ${data.total_added} agent(s)`); setSubmissionAgentInput(''); fetchSubmissionAgents() }
      else { const err = await res.json(); setError(err.detail || 'Failed to add agents') }
    } catch { setError('Network error') }
    setSubmissionAgentLoading(false)
  }

  const handleRemoveSubmissionAgent = async (agentId: string) => {
    try {
      const res = await fetch(API_URL + '/api/submission-agents/' + agencySlug + '/' + agentId, { method: 'DELETE', headers })
      if (res.ok) { setSuccess('Agent removed'); fetchSubmissionAgents() }
      else { const err = await res.json(); setError(err.detail || 'Failed to remove agent') }
    } catch { setError('Network error') }
  }

  const fetchDeals = useCallback(async () => {
    try {
      const res = await fetch(API_URL + '/api/deals/' + agencySlug + (isAdmin ? '' : '?agent_name=' + encodeURIComponent(user?.agent_name || '')), { headers })
      if (res.ok) { const data = await res.json(); setDealsSummary(data.summary || null) }
    } catch { /* ignore */ }
  }, [token, agencySlug, isAdmin, user?.agent_name])


  const fetchAgents = useCallback(async () => {
    if (!isAdmin) return
    try {
      const res = await fetch(API_URL + '/api/agencies/' + agencySlug + '/agents', { headers })
      if (res.ok) setAgents(await res.json())
    } catch { /* ignore */ }
    try {
      const res2 = await fetch(API_URL + '/api/agencies/' + agencySlug + '/ghl-agents', { headers })
      if (res2.ok) {
        const data = await res2.json()
        setGhlAgents(data.ghl_agents || [])
        // If agents were auto-created, refresh the agents list to include them
        if (data.auto_created && data.auto_created.length > 0) {
          const res3 = await fetch(API_URL + '/api/agencies/' + agencySlug + '/agents', { headers })
          if (res3.ok) setAgents(await res3.json())
        }
      }
    } catch { /* ignore */ }
  }, [token, agencySlug, isAdmin])

  const fetchSettings = useCallback(async () => {
    if (!isAdmin) return
    try {
      const res = await fetch(API_URL + '/api/agencies/' + agencySlug, { headers })
      if (res.ok) {
        const data = await res.json()
        setSettingsData({ ghl_api_key: data.ghl_api_key || '', ghl_location_id: data.ghl_location_id || '', ghl_agent_field_id: data.ghl_agent_field_id || '', ghl_premium_field_id: data.ghl_premium_field_id || '', ghl_advance_status_field_id: data.ghl_advance_status_field_id || '', ghl_paid_to_agent_field_id: data.ghl_paid_to_agent_field_id || '', calltools_api_key: data.calltools_api_key || '', calltools_team_id: data.calltools_team_id || '' })
      }
    } catch { /* ignore */ }
  }, [token, agencySlug, isAdmin])

  const fetchDashboardStats = useCallback(async () => {
    if (!isAdmin) return
    try {
      const res = await fetch(API_URL + '/api/deals/' + agencySlug + '/dashboard-stats', { headers })
      if (res.ok) setDashboardStats(await res.json())
    } catch { /* ignore */ }
  }, [token, agencySlug, isAdmin])

  const fetchBonusWeeks = useCallback(async (agentNameOverride?: string) => {
    const targetAgent = agentNameOverride || viewingAgentName
    if (isAdmin && !targetAgent) return
    setBonusWeeksLoading(true)
    try {
      const controller = new AbortController()
      const timeout = setTimeout(() => controller.abort(), 90000)
      const agentParam = isAdmin && targetAgent ? '?agent_name=' + encodeURIComponent(targetAgent) : ''
      const res = await fetch(API_URL + '/api/agent-portal/' + agencySlug + '/bonus-weeks' + agentParam, { headers, signal: controller.signal })
      clearTimeout(timeout)
      if (res.ok) {
        const data = await res.json()
        const weeks: BonusWeek[] = data.weeks || []
        setBonusWeeks(weeks)
        setSelectedWeek(weeks.length > 0 ? weeks[0].week_start : '')
        setWeekDeals(null)
      } else {
        setError('Failed to load bonus weeks')
      }
    } catch (e) {
      if (e instanceof DOMException && e.name === 'AbortError') {
        setError('Loading bonus weeks timed out — please try again')
      }
    } finally {
      setBonusWeeksLoading(false)
    }
  }, [token, agencySlug, isAdmin, viewingAgentName])

  const fetchWeekDeals = useCallback(async (weekStart: string) => {
    if (!weekStart) return
    const targetAgent = viewingAgentName
    if (isAdmin && !targetAgent) return
    setWeekLoading(true)
    try {
      const week = bonusWeeks.find(w => w.week_start === weekStart)
      if (!week) { setWeekLoading(false); return }
      const agentParam = isAdmin && targetAgent ? '&agent_name=' + encodeURIComponent(targetAgent) : ''
      const controller = new AbortController()
      const timeout = setTimeout(() => controller.abort(), 90000)
      // Only fetch deals here — billable hours fetched separately to prevent
      // a slow/OOM billable-hours request from blocking deals display
      const dealsRes = await fetch(API_URL + '/api/agent-portal/' + agencySlug + '/deals?week_start=' + week.week_start + '&week_end=' + week.week_end + agentParam, { headers, signal: controller.signal })
      clearTimeout(timeout)
      if (dealsRes.ok) setWeekDeals(await dealsRes.json())
    } catch (e) {
      if (e instanceof DOMException && e.name === 'AbortError') {
        setError('Loading deals timed out — please try again')
      }
    }
    setWeekLoading(false)
  }, [token, agencySlug, isAdmin, bonusWeeks, viewingAgentName])

  // Fetch billable hours independently — reads from pre-computed cache so
  // it's fast and won't block or crash the deals fetch
  const fetchBillableHours = useCallback(async (weekStart: string) => {
    if (!weekStart) return
    const targetAgent = viewingAgentName
    if (isAdmin && !targetAgent) return
    const week = bonusWeeks.find(w => w.week_start === weekStart)
    if (!week) return
    const agentParam = isAdmin && targetAgent ? '&agent_name=' + encodeURIComponent(targetAgent) : ''
    try {
      const res = await fetch(API_URL + '/api/agent-portal/' + agencySlug + '/billable-hours?week_start=' + week.week_start + '&week_end=' + week.week_end + agentParam, { headers })
      if (res.ok) setBillableHours(await res.json())
      else setBillableHours(null)
    } catch { setBillableHours(null) }
  }, [token, agencySlug, isAdmin, bonusWeeks, viewingAgentName])

  useEffect(() => { if (selectedWeek) { fetchWeekDeals(selectedWeek); fetchBillableHours(selectedWeek) } }, [selectedWeek, fetchWeekDeals, fetchBillableHours])

  useEffect(() => { if (!user || !token) { navigate('/'); return }; fetchDeals(); if (isAdmin) { fetchAgents(); fetchSettings(); fetchDashboardStats(); fetchHourlyWeeks(); fetchSubmissionAgents() } else { fetchBonusWeeks() } }, [user, token])

  // UX: Auto-dismiss toast notifications after 4 seconds
  useEffect(() => { if (success) { const t = setTimeout(() => setSuccess(''), 4000); return () => clearTimeout(t) } }, [success])
  useEffect(() => { if (error) { const t = setTimeout(() => setError(''), 6000); return () => clearTimeout(t) } }, [error])

  const handleViewAgent = (agentName: string) => {
    setViewingAgentName(agentName)
    setBonusWeeks([])
    setSelectedWeek('')
    setWeekDeals(null)
    setBillableHours(null)
    fetchBonusWeeks(agentName)
    // UX: auto-scroll to top
    window.scrollTo({ top: 0, behavior: 'smooth' })
  }

  const handleCloseAgentView = () => {
    setViewingAgentName(null)
    setBonusWeeks([])
    setSelectedWeek('')
    setWeekDeals(null)
    setBillableHours(null)
  }

  const handleCsvUpload = async () => {
    if (csvFiles.length === 0) { setError('Please select CSV files'); return }
    setLoading(true); setError(''); setUploadResults(null)
    try {
      const formData = new FormData()
      csvFiles.forEach(f => formData.append('files', f))
      const uploadHeaders: Record<string, string> = { Authorization: 'Bearer ' + (token || '') }
      const res = await fetch(API_URL + '/api/commission-sync/' + agencySlug + '/upload-multiple', { method: 'POST', headers: uploadHeaders, body: formData })
      if (res.ok) { const data = await res.json(); setUploadResults(data.results || []); setSuccess(`${data.files_processed} file(s) uploaded successfully`); setCsvFiles([]) } else { const err = await res.json(); setError(err.detail || 'Upload failed') }
    } catch { setError('Network error') }
    setLoading(false)
  }

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault(); setDragOver(false)
    const files = Array.from(e.dataTransfer.files).filter(f => f.name.toLowerCase().endsWith('.csv'))
    if (files.length > 0) setCsvFiles(prev => [...prev, ...files])
  }

  const handleFileSelect = (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = Array.from(e.target.files || []).filter(f => f.name.toLowerCase().endsWith('.csv'))
    if (files.length > 0) setCsvFiles(prev => [...prev, ...files])
    e.target.value = ''
  }

  const detectType = (name: string): string => {
    const u = name.toUpperCase()
    if (u.includes('_WA_') || u.startsWith('WA_')) return 'WA'
    if (u.includes('_WC_') || u.startsWith('WC_')) return 'WC'
    if (u.includes('_MC_') || u.startsWith('MC_')) return 'MC'
    return '?'
  }

  const typeColor = (t: string) => t === 'WA' ? 'text-blue-600 bg-blue-100' : t === 'WC' ? 'text-purple-600 bg-purple-100' : t === 'MC' ? 'text-amber-700 bg-amber-500/20' : 'text-red-600 bg-red-500/20'

  const handleDeactivateAgent = async (agentId: string) => {
    try {
      const res = await fetch(API_URL + '/api/agencies/' + agencySlug + '/agents/' + agentId + '/deactivate', { method: 'POST', headers })
      if (res.ok) { setSuccess('Agent deactivated'); fetchAgents() } else { setError('Failed to deactivate agent') }
    } catch { setError('Network error') }
  }

  const handleReactivateAgent = async (agentId: string) => {
    try {
      const res = await fetch(API_URL + '/api/agencies/' + agencySlug + '/agents/' + agentId + '/reactivate', { method: 'POST', headers })
      if (res.ok) { setSuccess('Agent reactivated'); fetchAgents() } else { setError('Failed to reactivate agent') }
    } catch { setError('Network error') }
  }

  const handleResetPassword = async () => {
    if (!resetPasswordEmail || !newPassword) { setError('Email and password required'); return }
    try {
      const res = await fetch(API_URL + '/api/agencies/' + agencySlug + '/agents/reset-password', { method: 'POST', headers, body: JSON.stringify({ email: resetPasswordEmail, new_password: newPassword }) })
      if (res.ok) { setSuccess('Password reset'); setResetPasswordEmail(''); setNewPassword('') } else { setError('Failed to reset password') }
    } catch { setError('Network error') }
  }

  const handleResetAllPasswords = async () => {
    if (!confirm('Reset ALL agent passwords to the default? Agents will be prompted to set a new password on next login.')) return
    try {
      const res = await fetch(`${API_URL}/api/agencies/${agency?.slug}/agents/reset-all-passwords`, { method: 'POST', headers: { Authorization: `Bearer ${token}` } })
      if (res.ok) { const data = await res.json(); setSuccess(`Reset ${data.reset_count} agent passwords to default (${data.default_password})`) } else { setError('Failed to reset passwords') }
    } catch { setError('Network error') }
  }

  const handleGenerateLogin = async (agentName: string) => {
    try {
      const res = await fetch(API_URL + '/api/agencies/' + agencySlug + '/agents/generate-login', { method: 'POST', headers, body: JSON.stringify({ agent_name: agentName }) })
      if (res.ok) { const data = await res.json(); setGeneratedCredentials({ email: data.email, password: data.password, agent_name: data.agent_name }); setSuccess('Login generated for ' + agentName); fetchAgents() }
      else { const err = await res.json(); setError(err.detail || 'Failed to generate login') }
    } catch { setError('Network error') }
  }

  const fetchHourlyWeeks = useCallback(async () => {
    if (!isAdmin) return
    try {
      const res = await fetch(API_URL + '/api/agent-portal/' + agencySlug + '/standard-weeks', { headers })
      if (res.ok) {
        const data = await res.json()
        const weeks: BonusWeek[] = data.weeks || []
        setHourlyWeeks(weeks)
        if (weeks.length > 0 && !hourlySelectedWeek) setHourlySelectedWeek(weeks[0].week_start)
      }
    } catch { /* ignore */ }
  }, [token, agencySlug, isAdmin])

  const fetchHourlyReport = useCallback(async (weekStart: string) => {
    if (!weekStart || !isAdmin) return
    const week = hourlyWeeks.find(w => w.week_start === weekStart)
    if (!week) return
    setHourlyLoading(true)
    setError('')
    try {
      const controller = new AbortController()
      const timeout = setTimeout(() => controller.abort(), 120000)
      const res = await fetch(API_URL + '/api/agent-portal/' + agencySlug + '/hourly-report?week_start=' + week.week_start + '&week_end=' + week.week_end, { headers, signal: controller.signal })
      clearTimeout(timeout)
      if (res.ok) { setHourlyReport(await res.json()) }
      else {
        const err = await res.json().catch(() => ({ detail: 'Failed to load hourly report' }))
        setError(err.detail || 'Failed to load hourly report')
        setHourlyReport(null)
      }
    } catch (e) {
      if (e instanceof DOMException && e.name === 'AbortError') {
        setError('Hourly report timed out. The first load may take up to 2 minutes while data is fetched from CallTools. Please try again — subsequent loads will be much faster.')
      } else {
        setError('Network error loading hourly report')
      }
      setHourlyReport(null)
    }
    setHourlyLoading(false)
  }, [token, agencySlug, isAdmin, hourlyWeeks])

  const exportHourlyCsv = () => {
    if (!hourlyReport) return
    const rows = [['Agent Name', 'Billable Hours', 'Available Hours', 'On Call Hours', 'Post Call Hours']]
    for (const a of hourlyReport.agents) {
      rows.push([a.agent_name, String(a.billable_hours), String(a.available_hours), String(a.on_call_hours), String(a.post_call_billable_hours)])
    }
    rows.push(['TOTAL', String(hourlyReport.total_billable_hours), '', '', ''])
    const csv = rows.map(r => r.map(c => '"' + c.replace(/"/g, '""') + '"').join(',')).join('\n')
    const blob = new Blob([csv], { type: 'text/csv' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = 'hourly-report-' + hourlyReport.week_start + '.csv'
    a.click()
    URL.revokeObjectURL(url)
  }

  const handleSaveSettings = async () => {
    setLoading(true); setError('')
    try {
      const res = await fetch(API_URL + '/api/agencies/' + agencySlug, { method: 'PUT', headers, body: JSON.stringify(settingsData) })
      if (res.ok) setSuccess('Settings saved'); else setError('Failed to save settings')
    } catch { setError('Network error') }
    setLoading(false)
  }

  const handleLogout = () => { logout(); navigate('/') }

  const adminMenuItems = [
    { id: 'dashboard' as AdminTab, label: 'Dashboard', icon: <LayoutDashboard className="w-5 h-5" /> },
    { id: 'commission' as AdminTab, label: 'Commission Sync', icon: <FileText className="w-5 h-5" /> },
    { id: 'agents' as AdminTab, label: 'Agent Management', icon: <Users className="w-5 h-5" /> },
    { id: 'hourly' as AdminTab, label: 'Hourly Report', icon: <Clock className="w-5 h-5" /> },
    { id: 'submission_agents' as AdminTab, label: 'Submission Agents', icon: <UserPlus className="w-5 h-5" /> },
    { id: 'audit' as AdminTab, label: 'Commission Audit', icon: <Search className="w-5 h-5" /> },
    { id: 'settings' as AdminTab, label: 'Settings', icon: <Settings className="w-5 h-5" /> },
  ]

  const agentMenuItems = [
    { id: 'dashboard' as AgentTab, label: 'Dashboard', icon: <LayoutDashboard className="w-5 h-5" /> },
    { id: 'deals' as AgentTab, label: 'My Deals', icon: <FileText className="w-5 h-5" /> },
  ]

  const menuItems = isAdmin ? adminMenuItems : agentMenuItems
  const currentTab = isAdmin ? adminTab : agentTab
  const setCurrentTab = (tab: string) => {
    // UX: clear messages on tab switch
    setError(''); setSuccess('')
    if (isAdmin) setAdminTab(tab as AdminTab); else setAgentTab(tab as AgentTab)
    // UX: scroll to top on tab change
    window.scrollTo({ top: 0, behavior: 'smooth' })
  }

  return (
    <div className="flex h-screen bg-slate-50">
      {mustChangePassword && <ChangePasswordModal />}
      {/* Sidebar */}
      <aside className={`${sidebarOpen ? 'w-64' : 'w-20'} bg-white border-r border-slate-200 flex flex-col shadow-sm transition-all duration-300 shrink-0`}>
        <div className="p-4 border-b border-slate-200 flex items-center gap-3">
          <button onClick={() => setSidebarOpen(!sidebarOpen)} className="p-2 rounded-lg hover:bg-slate-100 text-slate-400 hover:text-slate-700 transition"><Menu className="w-5 h-5" /></button>
          {sidebarOpen && <span className="text-slate-800 font-bold text-lg truncate">AP Insurance</span>}
        </div>
        <nav className="flex-1 p-3 space-y-1">
          {menuItems.map(item => (
            <button key={item.id} onClick={() => setCurrentTab(item.id)} className={`w-full flex items-center gap-3 px-3 py-3 rounded-xl text-sm font-medium transition-all ${currentTab === item.id ? 'bg-blue-50 text-blue-600 border border-blue-200' : 'text-slate-500 hover:text-slate-800 hover:bg-slate-100'}`}>
              {item.icon}
              {sidebarOpen && <span>{item.label}</span>}
            </button>
          ))}
        </nav>
        <div className="p-3 border-t border-slate-200 space-y-1">
                    <button onClick={() => navigate('/' + agencySlug)} className={`w-full flex items-center gap-3 px-3 py-2 rounded-lg text-slate-500 hover:text-amber-600 hover:bg-amber-50 transition text-sm ${sidebarOpen ? '' : 'justify-center'}`}>
                      <Trophy className="w-4 h-4" />
                      {sidebarOpen && <span>Leaderboard</span>}
                    </button>
          <div className={`flex items-center gap-3 px-3 py-2 ${sidebarOpen ? '' : 'justify-center'}`}>
            <div className="w-9 h-9 rounded-full bg-blue-600 flex items-center justify-center text-white font-bold text-sm shrink-0">{getInitials(user?.agent_name || user?.email || 'U')}</div>
            {sidebarOpen && <div className="flex-1 min-w-0"><div className="text-slate-800 text-sm font-medium truncate">{user?.agent_name || user?.email}</div><div className="text-slate-500 text-xs">{isAdmin ? 'Admin' : 'Agent'}</div></div>}
          </div>
          <button onClick={handleLogout} className={`w-full flex items-center gap-3 px-3 py-2 rounded-lg text-slate-400 hover:text-red-500 hover:bg-red-50 transition text-sm ${sidebarOpen ? '' : 'justify-center'}`}>
            <LogOut className="w-4 h-4" />
            {sidebarOpen && <span>Sign Out</span>}
          </button>
        </div>
      </aside>

      {/* Main Content */}
      <main className="flex-1 overflow-y-auto">
        {/* Sticky Header */}
        <div className="sticky top-0 z-30 bg-white/95 backdrop-blur-sm border-b border-slate-200">
          <div className="px-6 py-4 max-w-7xl mx-auto flex items-center justify-between">
            <div>
              <div className="flex items-center gap-2 text-slate-400 text-xs mb-1">
                <span>{agency?.name || 'Agency'}</span>
                <ChevronRight className="w-3 h-3" />
                <span className="text-slate-600">
                  {currentTab === 'dashboard' && (isAdmin ? 'Admin Dashboard' : 'My Dashboard')}
                  {currentTab === 'commission' && 'Commission Sync'}
                  {currentTab === 'agents' && 'Agent Management'}
                  {currentTab === 'hourly' && 'Hourly Report'}
                  {currentTab === 'submission_agents' && 'Submission Agents'}
                  {currentTab === 'audit' && 'Commission Audit'}
                  {currentTab === 'settings' && 'Settings'}
                  {currentTab === 'deals' && 'My Deals'}
                </span>
              </div>
              <h1 className="text-2xl font-bold text-slate-800">
                {currentTab === 'dashboard' && (isAdmin ? 'Admin Dashboard' : 'My Dashboard')}
                {currentTab === 'commission' && 'Commission Sync'}
                {currentTab === 'agents' && 'Agent Management'}
                {currentTab === 'hourly' && 'Hourly Report'}
                {currentTab === 'submission_agents' && 'Submission Agents'}
                {currentTab === 'audit' && 'Commission Audit'}
                {currentTab === 'settings' && 'Settings'}
                {currentTab === 'deals' && 'My Deals'}
              </h1>
            </div>
            <button onClick={() => { fetchDeals(); if (isAdmin) { fetchAgents(); fetchDashboardStats(); fetchSubmissionAgents() } }} className="flex items-center gap-2 px-4 py-2 bg-white border border-slate-300 rounded-lg text-slate-600 hover:text-slate-800 hover:border-blue-400 transition shadow-sm"><RefreshCw className="w-4 h-4" /> Refresh</button>
          </div>
        </div>
        <div className="p-6 max-w-7xl mx-auto">

          {/* Toast Notifications — fixed position, stacked, auto-dismiss */}
          {(error || success) && (
            <div className="fixed top-4 right-4 z-50 flex flex-col gap-3 max-w-md">
              {error && <div className="p-4 bg-white border border-red-300 rounded-xl text-red-600 shadow-lg flex items-center gap-2 shadow-lg shadow-red-100 animate-[slideIn_0.3s_ease-out]"><AlertCircle className="w-5 h-5 shrink-0" /><span className="flex-1 text-sm">{error}</span><button onClick={() => setError('')} className="ml-2 hover:text-red-800 transition"><X className="w-4 h-4" /></button></div>}
              {success && <div className="p-4 bg-white border border-emerald-300 rounded-xl text-emerald-600 shadow-lg flex items-center gap-2 shadow-lg shadow-emerald-100 animate-[slideIn_0.3s_ease-out]"><CheckCircle className="w-5 h-5 shrink-0" /><span className="flex-1 text-sm">{success}</span><button onClick={() => setSuccess('')} className="ml-2 hover:text-red-800 transition"><X className="w-4 h-4" /></button></div>}
            </div>
          )}

          {/* ===== DASHBOARD TAB ===== */}
          {currentTab === 'dashboard' && isAdmin && (
            <div>
              {/* Policy Lifecycle Cards */}
              <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4 mb-6">
                <div className="bg-white border border-slate-200 rounded-xl shadow-sm p-5">
                  <div className="flex items-center gap-3 mb-3"><div className="p-2 bg-blue-100 rounded-lg"><BarChart3 className="w-5 h-5 text-blue-600" /></div><span className="text-slate-500 text-sm">Total Deals</span></div>
                  <div className="text-3xl font-bold text-slate-800">{dashboardStats?.total_deals || 0}</div>
                  <div className="text-blue-600 text-sm mt-1">{formatCurrency(dashboardStats?.total_premium || 0)} total premium</div>
                </div>
                <div className="bg-white border border-slate-200 rounded-xl shadow-sm p-5">
                  <div className="flex items-center gap-3 mb-3"><div className="p-2 bg-emerald-500/20 rounded-lg"><CheckCircle className="w-5 h-5 text-emerald-600" /></div><span className="text-slate-500 text-sm">Active Policies</span></div>
                  <div className="text-3xl font-bold text-slate-800">{dashboardStats?.active_count || 0}</div>
                  <div className="text-emerald-600 text-sm mt-1">{formatCurrency(dashboardStats?.active_premium || 0)} premium</div>
                </div>
                <div className="bg-white border border-slate-200 rounded-xl shadow-sm p-5">
                  <div className="flex items-center gap-3 mb-3"><div className="p-2 bg-amber-500/20 rounded-lg"><Clock className="w-5 h-5 text-amber-600" /></div><span className="text-slate-500 text-sm">Pending Deals</span></div>
                  <div className="text-3xl font-bold text-slate-800">{dashboardStats?.pending_count || 0}</div>
                  <div className="text-amber-600 text-sm mt-1">{formatCurrency(dashboardStats?.pending_premium || 0)} premium</div>
                </div>
              </div>
              <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4 mb-6">
                <div className="bg-white border border-slate-200 rounded-xl shadow-sm p-5">
                  <div className="flex items-center gap-3 mb-3"><div className="p-2 bg-blue-500/20 rounded-lg"><Calendar className="w-5 h-5 text-blue-500" /></div><span className="text-slate-500 text-sm">Future Active</span></div>
                  <div className="text-3xl font-bold text-slate-800">{dashboardStats?.future_active_count || 0}</div>
                  <div className="text-blue-500 text-sm mt-1">{formatCurrency(dashboardStats?.future_active_premium || 0)} premium</div>
                </div>
                <div className="bg-white border border-slate-200 rounded-xl shadow-sm p-5">
                  <div className="flex items-center gap-3 mb-3"><div className="p-2 bg-red-500/20 rounded-lg"><AlertCircle className="w-5 h-5 text-red-600" /></div><span className="text-slate-500 text-sm">Cancelled</span></div>
                  <div className="text-3xl font-bold text-slate-800">{dashboardStats?.cancelled_count || 0}</div>
                  <div className="text-red-600 text-sm mt-1">{formatCurrency(dashboardStats?.cancelled_premium || 0)} premium</div>
                </div>
                <div className="bg-white border border-slate-200 rounded-xl shadow-sm p-5">
                  <div className="flex items-center gap-3 mb-3"><div className="p-2 bg-purple-100 rounded-lg"><XCircle className="w-5 h-5 text-purple-600" /></div><span className="text-slate-500 text-sm">Not Effectuated</span></div>
                  <div className="text-3xl font-bold text-slate-800">{dashboardStats?.not_effectuated_count || 0}</div>
                  <div className="text-purple-600 text-sm mt-1">{formatCurrency(dashboardStats?.not_effectuated_premium || 0)} premium</div>
                </div>
              </div>

              {/* Rates */}
              <div className="grid grid-cols-2 sm:grid-cols-4 gap-4 mb-8">
                <div className="bg-white border border-slate-200 rounded-xl shadow-sm p-4 text-center">
                  <div className="text-slate-400 text-xs uppercase mb-1">Effectuation Rate</div>
                  <div className="text-2xl font-bold text-emerald-600">{dashboardStats?.effectuation_rate || 0}%</div>
                </div>
                <div className="bg-white border border-slate-200 rounded-xl shadow-sm p-4 text-center">
                  <div className="text-slate-400 text-xs uppercase mb-1">Cancel Rate</div>
                  <div className="text-2xl font-bold text-red-600">{dashboardStats?.cancel_rate || 0}%</div>
                </div>
                <div className="bg-white border border-slate-200 rounded-xl shadow-sm p-4 text-center">
                  <div className="text-slate-400 text-xs uppercase mb-1">Not Effectuated Rate</div>
                  <div className="text-2xl font-bold text-purple-600">{dashboardStats?.not_effectuated_rate || 0}%</div>
                </div>
                <div className="bg-white border border-slate-200 rounded-xl shadow-sm p-4 text-center">
                  <div className="text-slate-400 text-xs uppercase mb-1">Pending Rate</div>
                  <div className="text-2xl font-bold text-amber-600">{dashboardStats?.pending_rate || 0}%</div>
                </div>
              </div>

              {/* Time-based Deal Cards */}
              <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
                <div className="bg-white border border-slate-200 rounded-xl shadow-sm p-4">
                  <div className="text-slate-400 text-xs uppercase mb-1">Today</div>
                  <div className="text-2xl font-bold text-slate-800">{dashboardStats?.today?.deals || 0} deals</div>
                  <div className="text-purple-600 text-sm">{formatCurrency(dashboardStats?.today?.premium || 0)}</div>
                </div>
                <div className="bg-white border border-slate-200 rounded-xl shadow-sm p-4">
                  <div className="text-slate-400 text-xs uppercase mb-1">This Week</div>
                  <div className="text-2xl font-bold text-slate-800">{dashboardStats?.week?.deals || 0} deals</div>
                  <div className="text-rose-600 text-sm">{formatCurrency(dashboardStats?.week?.premium || 0)}</div>
                </div>
                <div className="bg-white border border-slate-200 rounded-xl shadow-sm p-4">
                  <div className="text-slate-400 text-xs uppercase mb-1">This Month</div>
                  <div className="text-2xl font-bold text-slate-800">{dashboardStats?.month?.deals || 0} deals</div>
                  <div className="text-amber-700 text-sm">{formatCurrency(dashboardStats?.month?.premium || 0)}</div>
                </div>
              </div>
            </div>
          )}

          {/* ===== AGENT DASHBOARD TAB ===== */}
          {currentTab === 'dashboard' && !isAdmin && (
            <div>
              <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4 mb-8">
                <div className="bg-white border border-slate-200 rounded-xl shadow-sm p-5">
                  <div className="flex items-center gap-3 mb-3"><div className="p-2 bg-blue-100 rounded-lg"><TrendingUp className="w-5 h-5 text-blue-600" /></div><span className="text-slate-500 text-sm">Total Deals</span></div>
                  <div className="text-3xl font-bold text-slate-800">{dealsSummary?.total?.deals || 0}</div>
                  <div className="text-blue-600 text-sm mt-1">{formatCurrency(dealsSummary?.total?.premium || 0)} premium</div>
                </div>
                <div className="bg-white border border-slate-200 rounded-xl shadow-sm p-5">
                  <div className="flex items-center gap-3 mb-3"><div className="p-2 bg-purple-100 rounded-lg"><Zap className="w-5 h-5 text-purple-600" /></div><span className="text-slate-500 text-sm">Today</span></div>
                  <div className="text-3xl font-bold text-slate-800">{dealsSummary?.today?.deals || 0}</div>
                  <div className="text-purple-600 text-sm mt-1">{formatCurrency(dealsSummary?.today?.premium || 0)} premium</div>
                </div>
                <div className="bg-white border border-slate-200 rounded-xl shadow-sm p-5">
                  <div className="flex items-center gap-3 mb-3"><div className="p-2 bg-rose-500/20 rounded-lg"><Clock className="w-5 h-5 text-rose-600" /></div><span className="text-slate-500 text-sm">This Week</span></div>
                  <div className="text-3xl font-bold text-slate-800">{dealsSummary?.week?.deals || 0}</div>
                  <div className="text-rose-600 text-sm mt-1">{formatCurrency(dealsSummary?.week?.premium || 0)} premium</div>
                </div>
                <div className="bg-white border border-slate-200 rounded-xl shadow-sm p-5">
                  <div className="flex items-center gap-3 mb-3"><div className="p-2 bg-amber-500/20 rounded-lg"><DollarSign className="w-5 h-5 text-amber-700" /></div><span className="text-slate-500 text-sm">This Month</span></div>
                  <div className="text-3xl font-bold text-slate-800">{dealsSummary?.month?.deals || 0}</div>
                  <div className="text-amber-700 text-sm mt-1">{formatCurrency(dealsSummary?.month?.premium || 0)} premium</div>
                </div>
              </div>
            </div>
          )}

          {/* ===== COMMISSION SYNC TAB ===== */}
          {currentTab === 'commission' && isAdmin && (
            <div className="space-y-6">
              <div className="bg-white border border-slate-200 rounded-xl shadow-sm p-6">
                <h2 className="text-slate-800 text-lg font-semibold mb-4 flex items-center gap-2"><Upload className="w-5 h-5 text-blue-600" /> Upload Commission Statements</h2>
                <p className="text-slate-500 text-sm mb-4">Drop one or more CSV files below. Type is auto-detected from the filename (_WA_, _WC_, _MC_). Files are processed in order: WA first, then WC, then MC.</p>
                <div
                  onDragOver={e => { e.preventDefault(); setDragOver(true) }}
                  onDragLeave={() => setDragOver(false)}
                  onDrop={handleDrop}
                  onClick={() => fileInputRef.current?.click()}
                  className={`border-2 border-dashed rounded-xl p-8 text-center cursor-pointer transition-all ${dragOver ? 'border-blue-400 bg-blue-50' : 'border-slate-300 hover:border-blue-400 hover:bg-blue-50/50'}`}
                >
                  <Upload className={`w-10 h-10 mx-auto mb-3 ${dragOver ? 'text-blue-600' : 'text-slate-400'}`} />
                  <div className="text-slate-700 font-medium mb-1">Drag & drop CSV files here</div>
                  <div className="text-slate-500 text-sm">or click to browse</div>
                  <input ref={fileInputRef} type="file" accept=".csv" multiple onChange={handleFileSelect} className="hidden" />
                </div>

                {csvFiles.length > 0 && (
                  <div className="mt-4 space-y-2">
                    <div className="text-slate-600 text-sm font-medium mb-2">{csvFiles.length} file(s) queued</div>
                    {csvFiles.map((f, i) => {
                      const t = detectType(f.name)
                      return (
                        <div key={i} className="flex items-center justify-between bg-slate-50 rounded-lg px-4 py-2 border border-slate-200">
                          <div className="flex items-center gap-3">
                            <span className={`text-xs font-bold px-2 py-1 rounded ${typeColor(t)}`}>{t}</span>
                            <span className="text-slate-800 text-sm truncate max-w-xs">{f.name}</span>
                            <span className="text-slate-400 text-xs">{(f.size / 1024).toFixed(0)} KB</span>
                          </div>
                          <button onClick={(e) => { e.stopPropagation(); setCsvFiles(prev => prev.filter((_, j) => j !== i)) }} className="text-slate-400 hover:text-red-500 transition"><X className="w-4 h-4" /></button>
                        </div>
                      )
                    })}
                    {csvFiles.some(f => detectType(f.name) === '?') && (
                      <div className="flex items-center gap-2 text-red-600 text-sm mt-2"><AlertCircle className="w-4 h-4" /> Some files could not be identified. Filenames must contain _WA_, _WC_, or _MC_.</div>
                    )}
                    <div className="flex gap-3 mt-4">
                      <button onClick={handleCsvUpload} disabled={loading || csvFiles.some(f => detectType(f.name) === '?')} className="flex items-center gap-2 px-6 py-3 bg-blue-600 hover:bg-blue-700 text-white font-semibold rounded-lg transition-all disabled:opacity-50 shadow-sm disabled:cursor-not-allowed shadow-lg shadow-teal-500/20">
                        {loading ? <RotateCw className="w-4 h-4 animate-spin" /> : <Upload className="w-4 h-4" />}
                        {loading ? 'Processing...' : `Upload ${csvFiles.length} File${csvFiles.length > 1 ? 's' : ''} & Sync`}
                      </button>
                      <button onClick={() => setCsvFiles([])} className="px-4 py-3 bg-slate-100 text-slate-600 hover:bg-slate-200 rounded-lg text-sm font-medium transition">Clear All</button>
                    </div>
                  </div>
                )}
              </div>

              {uploadResults && uploadResults.length > 0 && (
                <div className="space-y-4">
                  {uploadResults.map((result, ri) => (
                    <div key={ri} className={`bg-white border rounded-xl p-6 shadow-sm ${(result as Record<string, unknown>).error ? 'border-red-200' : 'border-emerald-200'}`}>
                      <h3 className="text-slate-800 text-lg font-semibold mb-4 flex items-center gap-2">
                        {(result as Record<string, unknown>).error ? <AlertCircle className="w-5 h-5 text-red-600" /> : <CheckCircle className="w-5 h-5 text-emerald-600" />}
                        {String((result as Record<string, unknown>).statement_type || '')} — {String((result as Record<string, unknown>).file_name || '')}
                      </h3>
                      {(result as Record<string, unknown>).error ? (
                        <div className="text-red-600 text-sm">{String((result as Record<string, unknown>).error)}</div>
                      ) : (
                        <>
                          <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
                            {Object.entries(result).filter(([k, v]) => typeof v !== 'object' && k !== 'file_name').map(([key, val]) => (
                              <div key={key} className="bg-slate-50 border border-slate-200 rounded-lg p-3">
                                <div className="text-slate-400 text-xs uppercase">{key.replace(/_/g, ' ')}</div>
                                <div className="text-slate-800 text-lg font-bold mt-1">{String(val)}</div>
                              </div>
                            ))}
                          </div>
                          {Array.isArray((result as Record<string, unknown>).unmatched_records) && ((result as Record<string, unknown>).unmatched_records as Array<Record<string, string>>).length > 0 && (
                            <div className="mt-4">
                              <div className="text-slate-400 text-xs uppercase mb-2">Unmatched Policies</div>
                              <div className="space-y-1">
                                {((result as Record<string, unknown>).unmatched_records as Array<Record<string, string>>).map((u, i) => (
                                  <div key={i} className="text-sm text-slate-600 bg-slate-50 border border-slate-200 rounded px-3 py-1">{u.policy_number} — {u.insured_name || u.csv_agent}</div>
                                ))}
                              </div>
                            </div>
                          )}
                        </>
                      )}
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}

          {/* ===== AGENT MANAGEMENT TAB ===== */}
          {currentTab === 'agents' && isAdmin && (
            <div className="space-y-6">

              {/* Slide-out Agent Panel */}
              {viewingAgentName && (
                <>
                <div className="fixed inset-0 bg-black/30 z-40" onClick={handleCloseAgentView} />
                <div className="fixed top-0 right-0 h-full w-full max-w-3xl bg-white border-l border-slate-200 z-50 overflow-y-auto shadow-2xl animate-[slideInRight_0.3s_ease-out]">
                <div className="p-6 space-y-6">
                  <div className="flex items-center justify-between">
                    <h2 className="text-slate-800 text-xl font-bold flex items-center gap-3">
                      <div className={`w-10 h-10 rounded-full flex items-center justify-center text-white font-bold bg-gradient-to-br ${getAvatarColor(viewingAgentName)}`}>{getInitials(viewingAgentName)}</div>
                      {viewingAgentName}&apos;s Weekly View
                    </h2>
                    <button onClick={handleCloseAgentView} className="flex items-center gap-1 px-4 py-2 rounded-lg bg-slate-100 border border-slate-200 text-slate-600 hover:bg-slate-200 text-sm font-medium transition"><PanelRightClose className="w-4 h-4" /> Close</button>
                  </div>
                  <div className="flex items-center gap-4 flex-wrap">
                    <label className="text-slate-600 text-sm font-medium">Bonus Week</label>
                    {bonusWeeksLoading ? (
                      <div className="flex items-center gap-2 text-slate-500 text-sm"><RefreshCw className="w-4 h-4 text-blue-600 animate-spin" /> Loading weeks...</div>
                    ) : (
                      <select value={selectedWeek} onChange={e => setSelectedWeek(e.target.value)} className="px-4 py-2 bg-white border border-slate-300 rounded-lg text-slate-800 focus:border-blue-500 outline-none transition min-w-[280px]">
                        {bonusWeeks.length === 0 && <option value="">No bonus weeks found</option>}
                        {bonusWeeks.map(w => <option key={w.week_start} value={w.week_start}>{w.label}</option>)}
                      </select>
                    )}
                    {weekLoading && !bonusWeeksLoading && <RefreshCw className="w-4 h-4 text-blue-600 animate-spin" />}
                  </div>
                  {weekDeals && (
                    <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
                      <div className="bg-white border border-slate-200 rounded-xl shadow-sm p-5">
                        <div className="text-slate-500 text-sm mb-1">Submitted This Week</div>
                        <div className="text-3xl font-bold text-slate-800">{weekDeals.submitted_count}</div>
                        <div className="text-blue-600 text-xs mt-1">{formatCurrency(weekDeals.submitted_premium)} premium</div>
                      </div>
                      <div className="bg-white border border-slate-200 rounded-xl shadow-sm p-5">
                        <div className="text-slate-500 text-sm mb-1">Payable This Week</div>
                        <div className="text-3xl font-bold text-slate-800">{weekDeals.payable_count}</div>
                        <div className="text-emerald-600 text-xs mt-1">{formatCurrency(weekDeals.payable_premium)} premium</div>
                      </div>
                      <div className="bg-white border border-slate-200 rounded-xl shadow-sm p-5">
                        <div className="text-slate-500 text-sm mb-1">Total Deals</div>
                        <div className="text-3xl font-bold text-slate-800">{weekDeals.all_deals_count}</div>
                        <div className="text-purple-600 text-xs mt-1">across all weeks</div>
                      </div>
                    </div>
                  )}
                  <div className="bg-white border border-slate-200 rounded-xl shadow-sm overflow-hidden">
                    <div className="px-6 py-4 border-b border-slate-200 flex items-center justify-between">
                      <h2 className="text-slate-800 text-lg font-semibold flex items-center gap-2"><FileText className="w-5 h-5 text-blue-600" /> Submitted This Week</h2>
                      <span className="text-slate-500 text-sm">{weekDeals?.submitted_count || 0} deals</span>
                    </div>
                    <div className="overflow-x-auto">
                      <table className="w-full">
                        <thead><tr className="border-b border-slate-200">
                          <th className="text-left px-6 py-3 text-xs font-medium text-slate-500 uppercase tracking-wider">Customer</th>
                          <th className="text-left px-6 py-3 text-xs font-medium text-slate-500 uppercase tracking-wider">Date Submitted</th>
                          <th className="text-left px-6 py-3 text-xs font-medium text-slate-500 uppercase tracking-wider">Policy #</th>
                          <th className="text-left px-6 py-3 text-xs font-medium text-slate-500 uppercase tracking-wider">Type</th>
                          <th className="text-left px-6 py-3 text-xs font-medium text-slate-500 uppercase tracking-wider">Effective Date</th>
                          <th className="text-left px-6 py-3 text-xs font-medium text-slate-500 uppercase tracking-wider">Draft Date</th>
                          <th className="text-left px-6 py-3 text-xs font-medium text-slate-500 uppercase tracking-wider">Premium</th>
                        </tr></thead>
                        <tbody className="divide-y divide-slate-100">
                          {weekDeals?.submitted_deals.map((deal, i) => (
                            <tr key={deal.id || i} className="hover:bg-slate-50 transition-colors">
                              <td className="px-6 py-3 text-sm text-slate-800">{deal.contact_name}</td>
                              <td className="px-6 py-3 text-sm text-slate-500">{deal.date_added ? fmtDate(deal.date_added) : '\u2014'}</td>
                              <td className="px-6 py-3 text-sm text-slate-600">{deal.policy_number || '\u2014'}</td>
                              <td className="px-6 py-3 text-sm text-slate-600">{deal.plan_name || '\u2014'}</td>
                              <td className="px-6 py-3 text-sm text-slate-500">{deal.effective_date ? fmtDate(deal.effective_date) : '\u2014'}</td>
                              <td className="px-6 py-3 text-sm text-slate-500">{deal.premium_draft_date ? fmtDate(deal.premium_draft_date) : '\u2014'}</td>
                              <td className="px-6 py-3 text-sm font-semibold text-blue-600">{formatCurrency(deal.premium)}</td>
                            </tr>
                          ))}
                          {(!weekDeals || weekDeals.submitted_deals.length === 0) && (
                            <tr><td colSpan={7} className="px-6 py-8 text-center text-slate-400">No deals submitted this week</td></tr>
                          )}
                        </tbody>
                      </table>
                    </div>
                  </div>
                  <div className="bg-white border border-slate-200 rounded-xl shadow-sm overflow-hidden">
                    <div className="px-6 py-4 border-b border-slate-200 flex items-center justify-between">
                      <h2 className="text-slate-800 text-lg font-semibold flex items-center gap-2"><DollarSign className="w-5 h-5 text-emerald-600" /> Payable This Week</h2>
                      <span className="text-slate-500 text-sm">{weekDeals?.payable_count || 0} deals</span>
                    </div>
                    <div className="overflow-x-auto">
                      <table className="w-full">
                        <thead><tr className="border-b border-slate-200">
                          <th className="text-left px-6 py-3 text-xs font-medium text-slate-500 uppercase tracking-wider">Customer</th>
                          <th className="text-left px-6 py-3 text-xs font-medium text-slate-500 uppercase tracking-wider">Draft Date</th>
                          <th className="text-left px-6 py-3 text-xs font-medium text-slate-500 uppercase tracking-wider">Policy #</th>
                          <th className="text-left px-6 py-3 text-xs font-medium text-slate-500 uppercase tracking-wider">Type</th>
                          <th className="text-left px-6 py-3 text-xs font-medium text-slate-500 uppercase tracking-wider">Effective Date</th>
                          <th className="text-left px-6 py-3 text-xs font-medium text-slate-500 uppercase tracking-wider">Date Submitted</th>
                          <th className="text-left px-6 py-3 text-xs font-medium text-slate-500 uppercase tracking-wider">Premium</th>
                          <th className="text-left px-6 py-3 text-xs font-medium text-slate-500 uppercase tracking-wider">Status</th>
                        </tr></thead>
                        <tbody className="divide-y divide-slate-100">
                          {weekDeals?.payable_deals.map((deal, i) => (
                            <tr key={deal.id || i} className="hover:bg-slate-50 transition-colors">
                              <td className="px-6 py-3 text-sm text-slate-800">{deal.contact_name}</td>
                              <td className="px-6 py-3 text-sm text-slate-500">{deal.premium_draft_date ? fmtDate(deal.premium_draft_date) : '\u2014'}</td>
                              <td className="px-6 py-3 text-sm text-slate-600">{deal.policy_number || '\u2014'}</td>
                              <td className="px-6 py-3 text-sm text-slate-600">{deal.plan_name || '\u2014'}</td>
                              <td className="px-6 py-3 text-sm text-slate-500">{deal.effective_date ? fmtDate(deal.effective_date) : '\u2014'}</td>
                              <td className="px-6 py-3 text-sm text-slate-500">{deal.date_added ? fmtDate(deal.date_added) : '\u2014'}</td>
                              <td className="px-6 py-3 text-sm font-semibold text-emerald-600">{formatCurrency(deal.premium)}</td>
                              <td className="px-6 py-3"><span className="text-xs px-2 py-1 rounded-full font-medium bg-emerald-100 text-emerald-700">{deal.status}</span></td>
                            </tr>
                          ))}
                          {(!weekDeals || weekDeals.payable_deals.length === 0) && (
                            <tr><td colSpan={8} className="px-6 py-8 text-center text-slate-400">No payable deals this week</td></tr>
                          )}
                        </tbody>
                      </table>
                    </div>
                  </div>
                  <div className="bg-white border border-red-200 rounded-xl shadow-sm overflow-hidden">
                    <div className="px-6 py-4 border-b border-red-100 flex items-center justify-between">
                      <h2 className="text-slate-800 text-lg font-semibold flex items-center gap-2"><AlertTriangle className="w-5 h-5 text-red-600" /> Cancels / Failed</h2>
                      <span className="text-slate-500 text-sm">{weekDeals?.failed_count || 0} deals</span>
                    </div>
                    <div className="overflow-x-auto">
                      <table className="w-full">
                        <thead><tr className="border-b border-red-100">
                          <th className="text-left px-6 py-3 text-xs font-medium text-slate-500 uppercase tracking-wider">Customer</th>
                          <th className="text-left px-6 py-3 text-xs font-medium text-slate-500 uppercase tracking-wider">Date Submitted</th>
                          <th className="text-left px-6 py-3 text-xs font-medium text-slate-500 uppercase tracking-wider">Policy #</th>
                          <th className="text-left px-6 py-3 text-xs font-medium text-slate-500 uppercase tracking-wider">Type</th>
                          <th className="text-left px-6 py-3 text-xs font-medium text-slate-500 uppercase tracking-wider">Effective Date</th>
                          <th className="text-left px-6 py-3 text-xs font-medium text-slate-500 uppercase tracking-wider">Draft Date</th>
                          <th className="text-left px-6 py-3 text-xs font-medium text-slate-500 uppercase tracking-wider">Premium</th>
                          <th className="text-left px-6 py-3 text-xs font-medium text-slate-500 uppercase tracking-wider">Status</th>
                          <th className="text-left px-6 py-3 text-xs font-medium text-slate-500 uppercase tracking-wider">Reason</th>
                        </tr></thead>
                        <tbody className="divide-y divide-red-50">
                          {weekDeals?.failed_deals.map((deal, i) => (
                            <tr key={deal.id || i} className="hover:bg-red-50 transition-colors">
                              <td className="px-6 py-3 text-sm text-slate-800">{deal.contact_name}</td>
                              <td className="px-6 py-3 text-sm text-slate-500">{deal.date_added ? fmtDate(deal.date_added) : '\u2014'}</td>
                              <td className="px-6 py-3 text-sm text-slate-600">{deal.policy_number || '\u2014'}</td>
                              <td className="px-6 py-3 text-sm text-slate-600">{deal.plan_name || '\u2014'}</td>
                              <td className="px-6 py-3 text-sm text-slate-500">{deal.effective_date ? fmtDate(deal.effective_date) : '\u2014'}</td>
                              <td className="px-6 py-3 text-sm text-slate-500">{deal.premium_draft_date ? fmtDate(deal.premium_draft_date) : '\u2014'}</td>
                              <td className="px-6 py-3 text-sm font-semibold text-red-600">{formatCurrency(deal.premium)}</td>
                              <td className="px-6 py-3"><span className={`text-xs px-2 py-1 rounded-full font-medium ${deal.status === 'Chargeback' ? 'bg-red-100 text-red-700' : 'bg-amber-100 text-amber-700'}`}>{deal.status}</span></td>
                              <td className="px-6 py-3 text-sm text-slate-500">{deal.reason || '\u2014'}</td>
                            </tr>
                          ))}
                          {(!weekDeals || weekDeals.failed_deals.length === 0) && (
                            <tr><td colSpan={9} className="px-6 py-8 text-center text-slate-400">No cancelled or failed deals this week</td></tr>
                          )}
                        </tbody>
                      </table>
                    </div>
                  </div>
                </div>
                </div>
                </>
              )}

              {/* Password Reset */}
              <div className="bg-white border border-slate-200 rounded-xl shadow-sm p-6">
                <h2 className="text-slate-800 text-lg font-semibold mb-4 flex items-center gap-2"><Key className="w-5 h-5 text-blue-600" /> Reset Agent Password</h2>
                <div className="flex gap-4 items-end">
                  <div className="flex-1">
                    <label className="block text-xs font-medium text-slate-500 mb-1">Agent Email</label>
                    <input type="email" value={resetPasswordEmail} onChange={e => setResetPasswordEmail(e.target.value)} className="w-full px-3 py-2 bg-white border border-slate-300 rounded-lg text-slate-800 text-sm focus:border-blue-500 outline-none" placeholder="agent@example.com" />
                  </div>
                  <div className="flex-1">
                    <label className="block text-xs font-medium text-slate-500 mb-1">New Password</label>
                    <input type="text" value={newPassword} onChange={e => setNewPassword(e.target.value)} className="w-full px-3 py-2 bg-white border border-slate-300 rounded-lg text-slate-800 text-sm focus:border-blue-500 outline-none" placeholder="New password" />
                  </div>
                  <button onClick={handleResetPassword} className="px-5 py-2 bg-blue-600 text-white font-medium rounded-lg text-sm hover:bg-blue-700 transition-all shadow-sm">Reset</button>
                </div>
              </div>

              {generatedCredentials && (
                <div className="bg-emerald-50 border border-emerald-200 rounded-xl p-6">
                  <h3 className="text-emerald-600 font-semibold mb-3 flex items-center gap-2"><Key className="w-5 h-5" /> Generated Credentials for {generatedCredentials.agent_name}</h3>
                  <div className="bg-slate-50 rounded-lg p-4 font-mono text-sm space-y-2 border border-slate-200">
                    <div className="flex items-center justify-between"><span className="text-slate-500">Username:</span><span className="text-slate-800">{generatedCredentials.email}</span></div>
                    <div className="flex items-center justify-between"><span className="text-slate-500">Password:</span><span className="text-slate-800">{generatedCredentials.password}</span></div>
                  </div>
                  <p className="text-slate-400 text-xs mt-3">Agent will be prompted to set their own password on first login.</p>
                  <button onClick={() => setGeneratedCredentials(null)} className="mt-3 px-4 py-1.5 text-xs bg-slate-100 text-slate-600 hover:bg-slate-200 rounded-lg transition">Dismiss</button>
                </div>
              )}

              {/* New Agent Onboarding */}
              {ghlAgents.filter(a => !a.has_login).length > 0 && (
                <div className="bg-amber-50 border border-amber-200 rounded-xl p-6">
                  <h2 className="text-amber-700 text-lg font-semibold mb-2 flex items-center gap-2"><AlertCircle className="w-5 h-5" /> New Agent Onboarding</h2>
                  <p className="text-slate-500 text-sm mb-4">These agents have submitted deals in GHL but do not have a portal login yet.</p>
                  <div className="space-y-2">
                    {ghlAgents.filter(a => !a.has_login).map(agent => (
                      <div key={agent.agent_name} className="flex items-center justify-between p-3 bg-white border border-slate-200 rounded-lg shadow-sm">
                        <div className="flex items-center gap-3">
                          <div className={`w-10 h-10 rounded-full flex items-center justify-center text-white font-bold bg-gradient-to-br ${getAvatarColor(agent.agent_name)}`}>{getInitials(agent.agent_name)}</div>
                          <div><div className="text-slate-800 font-medium">{agent.agent_name}</div><div className="text-slate-400 text-xs">{agent.deal_count} deals in GHL</div></div>
                        </div>
                        <div className="flex items-center gap-2">
                          <button onClick={() => handleViewAgent(agent.agent_name)} className="flex items-center gap-1 px-3 py-1.5 rounded-lg bg-slate-100 text-blue-600 hover:bg-blue-50 text-xs font-medium transition"><BarChart3 className="w-3 h-3" /> View</button>
                          <button onClick={() => handleGenerateLogin(agent.agent_name)} className="flex items-center gap-1 px-4 py-2 rounded-lg bg-blue-600 text-white text-xs font-semibold hover:bg-blue-700 transition-all shadow-sm"><Key className="w-3 h-3" /> Create Account</button>
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {/* Active Agents */}
              <div className="bg-white border border-slate-200 rounded-xl shadow-sm overflow-hidden">
                <div className="px-6 py-4 border-b border-slate-200 flex items-center justify-between">
                  <h2 className="text-slate-800 text-lg font-semibold flex items-center gap-2"><Users className="w-5 h-5 text-blue-600" /> Active Agents</h2>
                  <div className="flex items-center gap-3">
                    <button onClick={handleResetAllPasswords} className="flex items-center gap-1 px-3 py-1.5 rounded-lg bg-amber-50 text-amber-700 border border-amber-200 hover:bg-amber-100 text-xs font-medium transition"><RotateCw className="w-3 h-3" /> Reset All Passwords</button>
                    <span className="text-slate-500 text-sm">{agents.filter(a => a.is_active).length} active</span>
                  </div>
                </div>
                <div className="divide-y divide-slate-100">
                  {agents.filter(a => a.is_active).sort((a, b) => a.agent_name.localeCompare(b.agent_name)).map(agent => (
                    <div key={agent.id} className="flex items-center justify-between px-6 py-4 hover:bg-slate-50 transition-colors">
                      <div className="flex items-center gap-3">
                        <div className={`w-10 h-10 rounded-full flex items-center justify-center text-white font-bold bg-gradient-to-br ${getAvatarColor(agent.agent_name)}`}>{getInitials(agent.agent_name)}</div>
                        <div><div className="text-slate-800 font-medium">{agent.agent_name}</div><div className="text-slate-400 text-xs">{agent.email}</div></div>
                      </div>
                      <div className="flex items-center gap-2">
                        <button onClick={() => handleViewAgent(agent.agent_name)} className="flex items-center gap-1 px-3 py-1.5 rounded-lg bg-slate-100 text-blue-600 hover:bg-blue-50 text-xs font-medium transition"><BarChart3 className="w-3 h-3" /> View</button>
                        <button onClick={() => handleDeactivateAgent(agent.id)} className="flex items-center gap-1 px-3 py-1.5 rounded-lg bg-red-50 text-red-600 hover:bg-red-100 text-xs font-medium transition"><UserX className="w-3 h-3" /> Deactivate</button>
                      </div>
                    </div>
                  ))}
                  {agents.filter(a => a.is_active).length === 0 && (
                    <div className="px-6 py-8 text-center text-slate-400">No agent accounts created yet. Use the onboarding section above to create accounts.</div>
                  )}
                </div>
              </div>

              {/* Inactive Agents */}
              {agents.filter(a => !a.is_active).length > 0 && (
                <div className="bg-white border border-slate-200 rounded-xl shadow-sm overflow-hidden">
                  <div className="px-6 py-4 border-b border-slate-200 cursor-pointer select-none" onClick={() => setInactiveCollapsed(!inactiveCollapsed)}>
                    <h2 className="text-slate-800 text-lg font-semibold flex items-center gap-2">
                      {inactiveCollapsed ? <ChevronRight className="w-5 h-5 text-slate-400 transition-transform" /> : <ChevronDown className="w-5 h-5 text-slate-400 transition-transform" />}
                      <UserX className="w-5 h-5 text-slate-400" /> Inactive Agents
                      <span className="text-slate-400 text-sm font-normal ml-1">{agents.filter(a => !a.is_active).length} agents</span>
                    </h2>
                  </div>
                  {!inactiveCollapsed && (
                    <div className="divide-y divide-slate-100">
                      {agents.filter(a => !a.is_active).sort((a, b) => a.agent_name.localeCompare(b.agent_name)).map(agent => (
                        <div key={agent.id} className="flex items-center justify-between px-6 py-4 hover:bg-slate-50 transition-colors opacity-60">
                          <div className="flex items-center gap-3">
                            <div className="w-10 h-10 rounded-full flex items-center justify-center text-white font-bold bg-slate-400">{getInitials(agent.agent_name)}</div>
                            <div><div className="text-slate-600 font-medium">{agent.agent_name}</div><div className="text-slate-400 text-xs">{agent.email}</div></div>
                          </div>
                          <button onClick={() => handleReactivateAgent(agent.id)} className="flex items-center gap-1 px-3 py-1.5 rounded-lg bg-emerald-50 text-emerald-600 hover:bg-emerald-100 text-xs font-medium transition"><UserCheck className="w-3 h-3" /> Reactivate</button>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              )}
            </div>
          )}

          {/* ===== HOURLY REPORT TAB (Admin) ===== */}
          {currentTab === 'hourly' && isAdmin && (
            <div className="space-y-6">
              <div className="flex items-center gap-4 flex-wrap">
                <label className="text-slate-600 text-sm font-medium">Week</label>
                <select value={hourlySelectedWeek} onChange={e => setHourlySelectedWeek(e.target.value)} className="px-4 py-2 bg-white border border-slate-300 rounded-lg text-slate-800 focus:border-blue-500 outline-none transition min-w-[280px]">
                  {hourlyWeeks.map(w => <option key={w.week_start} value={w.week_start}>{w.label}</option>)}
                </select>
                <button onClick={() => fetchHourlyReport(hourlySelectedWeek)} disabled={hourlyLoading || !hourlySelectedWeek} className="flex items-center gap-2 px-4 py-2 bg-blue-600 hover:bg-blue-700 text-white font-semibold rounded-lg transition-all disabled:opacity-50 shadow-sm">
                  {hourlyLoading ? <RotateCw className="w-4 h-4 animate-spin" /> : <RefreshCw className="w-4 h-4" />}
                  {hourlyLoading ? 'Fetching from CallTools...' : 'Load Report'}
                </button>
                {hourlyReport && (
                  <button onClick={exportHourlyCsv} className="flex items-center gap-2 px-4 py-2 bg-emerald-50 border border-emerald-200 text-emerald-600 hover:bg-emerald-100 font-semibold rounded-lg transition-all">
                    <Download className="w-4 h-4" /> Export CSV
                  </button>
                )}
              </div>

              {hourlyReport && (
                <>
                  <div className="grid grid-cols-1 sm:grid-cols-1 gap-4">
                    <div className="bg-white border border-slate-200 rounded-xl shadow-sm p-5">
                      <div className="text-slate-500 text-sm mb-1">Total Billable Hours</div>
                      <div className="text-3xl font-bold text-slate-800">{hourlyReport.total_billable_hours}h</div>
                    </div>
                  </div>

                  <div className="bg-white border border-slate-200 rounded-xl shadow-sm overflow-hidden">
                    <div className="p-4 border-b border-slate-200 flex items-center justify-between">
                      <h3 className="text-slate-800 font-semibold flex items-center gap-2"><Clock className="w-5 h-5 text-rose-600" /> Agent Hours — {hourlyReport.week_start} to {hourlyReport.week_end}</h3>
                      <span className="text-slate-500 text-sm">{hourlyReport.agents.length} agents</span>
                    </div>
                    <div className="overflow-x-auto">
                      <table className="w-full">
                        <thead>
                          <tr className="border-b border-slate-200">
                            <th className="text-left px-6 py-3 text-xs font-medium text-slate-500 uppercase">Agent</th>
                            <th className="text-right px-6 py-3 text-xs font-medium text-slate-500 uppercase">Billable</th>
                            <th className="text-right px-6 py-3 text-xs font-medium text-slate-500 uppercase">Available</th>
                            <th className="text-right px-6 py-3 text-xs font-medium text-slate-500 uppercase">On Call</th>
                            <th className="text-right px-6 py-3 text-xs font-medium text-slate-500 uppercase">Post Call</th>
                          </tr>
                        </thead>
                        <tbody>
                          {hourlyReport.agents.map(agent => (
                            <tr key={agent.agent_name} className="hover:bg-slate-50 transition-colors border-b border-slate-200/50">
                              <td className="px-6 py-3 text-sm text-slate-800 font-medium">{agent.agent_name}</td>
                              <td className="px-6 py-3 text-sm text-slate-800 text-right font-semibold">{agent.billable_hours}h</td>
                              <td className="px-6 py-3 text-sm text-slate-600 text-right">{agent.available_hours}h</td>
                              <td className="px-6 py-3 text-sm text-slate-600 text-right">{agent.on_call_hours}h</td>
                              <td className="px-6 py-3 text-sm text-slate-600 text-right">{agent.post_call_billable_hours}h</td>
                            </tr>
                          ))}
                          <tr className="bg-slate-100 font-bold">
                            <td className="px-6 py-3 text-sm text-slate-800">TOTAL</td>
                            <td className="px-6 py-3 text-sm text-slate-800 text-right">{hourlyReport.total_billable_hours}h</td>
                            <td className="px-6 py-3" colSpan={3}></td>
                          </tr>
                        </tbody>
                      </table>
                    </div>
                  </div>
                </>
              )}

              {!hourlyReport && !hourlyLoading && (
                <div className="text-center py-12 text-slate-400">
                  <Clock className="w-12 h-12 mx-auto mb-3 opacity-20" />
                  <p>Select a week and click "Load Report" to view agent hours</p>
                </div>
              )}
            </div>
          )}

          {/* ===== SUBMISSION AGENTS TAB ===== */}
          {currentTab === 'submission_agents' && isAdmin && (
            <div className="space-y-6">
              <div className="bg-white border border-slate-200 rounded-xl shadow-sm p-6">
                <h2 className="text-slate-800 text-lg font-semibold mb-4 flex items-center gap-2"><UserPlus className="w-5 h-5 text-blue-600" /> Add Submission Agents</h2>
                <p className="text-slate-500 text-sm mb-4">Enter agent names below (one per line). Names will be automatically converted to ALL CAPS and duplicates are skipped.</p>
                <textarea
                  value={submissionAgentInput}
                  onChange={e => setSubmissionAgentInput(e.target.value)}
                  placeholder={"JOHN SMITH\nJANE DOE\nBOB JOHNSON"}
                  rows={6}
                  className="w-full px-4 py-3 bg-slate-50 border border-slate-300 rounded-lg text-slate-800 focus:border-blue-500 outline-none transition font-mono text-sm"
                />
                <button onClick={handleAddSubmissionAgents} disabled={submissionAgentLoading || !submissionAgentInput.trim()} className="mt-4 flex items-center gap-2 px-6 py-3 bg-blue-600 hover:bg-blue-700 text-white font-semibold rounded-lg transition-all disabled:opacity-50 disabled:cursor-not-allowed shadow-sm">
                  {submissionAgentLoading ? <RotateCw className="w-4 h-4 animate-spin" /> : <UserPlus className="w-4 h-4" />}
                  {submissionAgentLoading ? 'Adding...' : 'Add Agents'}
                </button>
              </div>

              <div className="bg-white border border-slate-200 rounded-xl shadow-sm overflow-hidden">
                <div className="px-6 py-4 border-b border-slate-200 flex items-center justify-between">
                  <h2 className="text-slate-800 text-lg font-semibold flex items-center gap-2"><Users className="w-5 h-5 text-blue-600" /> Current Submission Agents</h2>
                  <span className="text-slate-500 text-sm">{submissionAgents.length} agent{submissionAgents.length !== 1 ? 's' : ''}</span>
                </div>
                <div className="divide-y divide-slate-100">
                  {submissionAgents.map(agent => (
                    <div key={agent.id} className="flex items-center justify-between px-6 py-3 hover:bg-slate-50 transition-colors">
                      <span className="text-slate-800 font-medium">{agent.name}</span>
                      <button onClick={() => handleRemoveSubmissionAgent(agent.id)} className="flex items-center gap-1 px-3 py-1.5 rounded-lg bg-red-50 text-red-500 hover:bg-red-100 text-xs font-medium transition"><Trash2 className="w-3 h-3" /> Remove</button>
                    </div>
                  ))}
                  {submissionAgents.length === 0 && (
                    <div className="px-6 py-8 text-center text-slate-400">No submission agents added yet. Add agents above to populate the deal submission form dropdown.</div>
                  )}
                </div>
              </div>
            </div>
          )}


          {/* ===== COMMISSION AUDIT TAB ===== */}
          {currentTab === 'audit' && isAdmin && (() => {
            const runAudit = async () => {
              setAuditLoading(true); setError(''); setAuditResult(null); setAuditSelected(new Set())
              try {
                const res = await fetch(API_URL + '/api/commission-sync/' + agencySlug + '/audit', { headers })
                if (res.ok) { const data = await res.json(); setAuditResult(data) } else { setError('Audit failed: ' + (await res.text())) }
              } catch { setError('Network error running audit') }
              setAuditLoading(false)
            }
            const clearAll = async () => {
              if (!confirm('This will clear ALL commission data from ALL GHL contacts. Are you sure?')) return
              setAuditClearing(true); setError('')
              try {
                const res = await fetch(API_URL + '/api/commission-sync/' + agencySlug + '/audit/clear', { method: 'POST', headers })
                if (res.ok) { const data = await res.json(); setSuccess(data.message); setAuditResult(null) } else { setError('Clear failed: ' + (await res.text())) }
              } catch { setError('Network error') }
              setAuditClearing(false)
            }
            const clearSelected = async () => {
              if (auditSelected.size === 0) return
              if (!confirm(`Clear commission data from ${auditSelected.size} selected contacts?`)) return
              setAuditClearing(true); setError('')
              try {
                const res = await fetch(API_URL + '/api/commission-sync/' + agencySlug + '/audit/clear-selected', {
                  method: 'POST', headers: { ...headers, 'Content-Type': 'application/json' }, body: JSON.stringify({ contact_ids: Array.from(auditSelected) }),
                })
                if (res.ok) {
                  const data = await res.json(); setSuccess(data.message)
                  setAuditResult(prev => prev ? { ...prev, flagged: prev.flagged.filter(c => !auditSelected.has(c.contact_id)), contacts_with_commission: prev.contacts_with_commission - auditSelected.size } : null)
                  setAuditSelected(new Set())
                } else { setError('Clear failed: ' + (await res.text())) }
              } catch { setError('Network error') }
              setAuditClearing(false)
            }
            const toggleSelect = (id: string) => setAuditSelected(prev => { const n = new Set(prev); if (n.has(id)) n.delete(id); else n.add(id); return n })
            const toggleAll = () => {
              if (!auditResult) return
              const filtered = auditResult.flagged.filter(c => !auditSearch || c.name.toLowerCase().includes(auditSearch.toLowerCase()) || c.policy_number.includes(auditSearch))
              if (auditSelected.size === filtered.length) setAuditSelected(new Set())
              else setAuditSelected(new Set(filtered.map(c => c.contact_id)))
            }
            const filtered = auditResult?.flagged.filter(c => !auditSearch || c.name.toLowerCase().includes(auditSearch.toLowerCase()) || c.policy_number.includes(auditSearch)) || []
            return (
            <div className="space-y-6">
              <div className="bg-white border border-slate-200 rounded-xl shadow-sm p-6">
                <div className="flex items-center justify-between mb-6">
                  <h2 className="text-slate-800 text-lg font-semibold flex items-center gap-2"><Search className="w-5 h-5 text-blue-600" /> Commission Audit</h2>
                  <div className="flex gap-3">
                    <button onClick={runAudit} disabled={auditLoading} className="flex items-center gap-2 px-4 py-2 bg-blue-600 hover:bg-blue-700 text-white font-medium rounded-lg transition-all disabled:opacity-50 text-sm">
                      {auditLoading ? <RefreshCw className="w-4 h-4 animate-spin" /> : <Search className="w-4 h-4" />}
                      {auditLoading ? 'Scanning...' : 'Scan Contacts'}
                    </button>
                    {auditResult && auditResult.contacts_with_commission > 0 && (
                      <button onClick={clearAll} disabled={auditClearing} className="flex items-center gap-2 px-4 py-2 bg-red-600 hover:bg-red-700 text-white font-medium rounded-lg transition-all disabled:opacity-50 text-sm">
                        {auditClearing ? <RefreshCw className="w-4 h-4 animate-spin" /> : <Trash2 className="w-4 h-4" />}
                        Clear All
                      </button>
                    )}
                  </div>
                </div>
                <p className="text-slate-500 text-sm">Scan all GHL contacts to find those with commission data. Use this to audit, review, and optionally clear commission fields before re-uploading statements.</p>
              </div>

              {auditLoading && (
                <div className="bg-white border border-slate-200 rounded-xl shadow-sm p-12 text-center">
                  <RefreshCw className="w-10 h-10 text-blue-600 animate-spin mx-auto mb-4" />
                  <p className="text-slate-600 font-medium">Scanning all GHL contacts...</p>
                  <p className="text-slate-400 text-sm mt-1">This may take a few minutes for large locations</p>
                </div>
              )}

              {auditResult && (
                <>
                  <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
                    <div className="bg-white border border-slate-200 rounded-xl shadow-sm p-5">
                      <div className="text-slate-500 text-sm mb-1">Total Contacts</div>
                      <div className="text-3xl font-bold text-slate-800">{auditResult.total_contacts.toLocaleString()}</div>
                    </div>
                    <div className="bg-white border border-slate-200 rounded-xl shadow-sm p-5">
                      <div className="text-slate-500 text-sm mb-1">With Commission Data</div>
                      <div className="text-3xl font-bold text-amber-600">{auditResult.contacts_with_commission.toLocaleString()}</div>
                    </div>
                    <div className="bg-white border border-slate-200 rounded-xl shadow-sm p-5">
                      <div className="text-slate-500 text-sm mb-1">Without Commission Data</div>
                      <div className="text-3xl font-bold text-emerald-600">{(auditResult.total_contacts - auditResult.contacts_with_commission).toLocaleString()}</div>
                    </div>
                  </div>

                  {auditResult.contacts_with_commission > 0 && (
                    <div className="bg-white border border-slate-200 rounded-xl shadow-sm overflow-hidden">
                      <div className="px-6 py-4 border-b border-slate-200 flex items-center justify-between flex-wrap gap-3">
                        <h3 className="text-slate-800 font-semibold flex items-center gap-2"><AlertTriangle className="w-4 h-4 text-amber-500" /> Contacts with Commission Data ({filtered.length})</h3>
                        <div className="flex items-center gap-3">
                          <input type="text" placeholder="Search by name or policy..." value={auditSearch} onChange={e => setAuditSearch(e.target.value)} className="px-3 py-1.5 bg-white border border-slate-300 rounded-lg text-sm text-slate-800 focus:border-blue-500 outline-none transition w-64" />
                          {auditSelected.size > 0 && (
                            <button onClick={clearSelected} disabled={auditClearing} className="flex items-center gap-1.5 px-3 py-1.5 bg-red-600 hover:bg-red-700 text-white font-medium rounded-lg transition-all disabled:opacity-50 text-sm">
                              <Trash2 className="w-3.5 h-3.5" /> Clear {auditSelected.size} Selected
                            </button>
                          )}
                        </div>
                      </div>
                      <div className="overflow-x-auto max-h-[600px] overflow-y-auto">
                        <table className="w-full">
                          <thead className="sticky top-0 bg-slate-50"><tr className="border-b border-slate-200">
                            <th className="px-4 py-3 text-left"><input type="checkbox" checked={filtered.length > 0 && auditSelected.size === filtered.length} onChange={toggleAll} className="rounded" /></th>
                            <th className="text-left px-4 py-3 text-xs font-medium text-slate-500 uppercase tracking-wider">Name</th>
                            <th className="text-left px-4 py-3 text-xs font-medium text-slate-500 uppercase tracking-wider">Policy #</th>
                            <th className="text-left px-4 py-3 text-xs font-medium text-slate-500 uppercase tracking-wider">Commission Fields</th>
                          </tr></thead>
                          <tbody className="divide-y divide-slate-100">
                            {filtered.slice(0, 200).map(c => (
                              <tr key={c.contact_id} className={`hover:bg-slate-50 transition-colors ${auditSelected.has(c.contact_id) ? 'bg-blue-50' : ''}`}>
                                <td className="px-4 py-2"><input type="checkbox" checked={auditSelected.has(c.contact_id)} onChange={() => toggleSelect(c.contact_id)} className="rounded" /></td>
                                <td className="px-4 py-2 text-sm text-slate-800 font-medium">{c.name}</td>
                                <td className="px-4 py-2 text-sm text-slate-600">{c.policy_number || '—'}</td>
                                <td className="px-4 py-2 text-xs text-slate-500">
                                  <div className="flex flex-wrap gap-1">
                                    {Object.entries(c.commission_fields).slice(0, 5).map(([k, v]) => (
                                      <span key={k} className="bg-slate-100 px-2 py-0.5 rounded text-slate-600">{k}: {v}</span>
                                    ))}
                                    {Object.keys(c.commission_fields).length > 5 && <span className="text-slate-400">+{Object.keys(c.commission_fields).length - 5} more</span>}
                                  </div>
                                </td>
                              </tr>
                            ))}
                            {filtered.length > 200 && (
                              <tr><td colSpan={4} className="px-4 py-3 text-center text-slate-400 text-sm">Showing first 200 of {filtered.length} contacts. Use search to filter.</td></tr>
                            )}
                          </tbody>
                        </table>
                      </div>
                    </div>
                  )}
                </>
              )}

              {!auditResult && !auditLoading && (
                <div className="bg-white border border-slate-200 rounded-xl shadow-sm p-12 text-center">
                  <Search className="w-12 h-12 text-slate-300 mx-auto mb-3" />
                  <p className="text-slate-500">Click "Scan Contacts" to find all GHL contacts with commission data</p>
                </div>
              )}
            </div>
            )
          })()}

          {/* ===== SETTINGS TAB ===== */}
          {currentTab === 'settings' && isAdmin && (
            <div className="bg-white border border-slate-200 rounded-xl shadow-sm p-6">
              <h2 className="text-slate-800 text-lg font-semibold mb-6 flex items-center gap-2"><Settings className="w-5 h-5 text-blue-600" /> Agency Settings</h2>
              <div className="space-y-4 max-w-2xl">
                <div>
                  <label className="block text-sm font-medium text-slate-600 mb-1">GHL API Key</label>
                  <input type="password" value={settingsData.ghl_api_key} onChange={e => setSettingsData({ ...settingsData, ghl_api_key: e.target.value })} className="w-full px-4 py-3 bg-white border border-slate-300 rounded-lg text-slate-800 focus:border-blue-500 outline-none transition" />
                </div>
                <div>
                  <label className="block text-sm font-medium text-slate-600 mb-1">GHL Location ID</label>
                  <input type="text" value={settingsData.ghl_location_id} onChange={e => setSettingsData({ ...settingsData, ghl_location_id: e.target.value })} className="w-full px-4 py-3 bg-white border border-slate-300 rounded-lg text-slate-800 focus:border-blue-500 outline-none transition" />
                </div>
                <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                  <div>
                    <label className="block text-sm font-medium text-slate-600 mb-1">Agent Field ID</label>
                    <input type="text" value={settingsData.ghl_agent_field_id} onChange={e => setSettingsData({ ...settingsData, ghl_agent_field_id: e.target.value })} className="w-full px-4 py-3 bg-white border border-slate-300 rounded-lg text-slate-800 focus:border-blue-500 outline-none transition text-sm" />
                  </div>
                  <div>
                    <label className="block text-sm font-medium text-slate-600 mb-1">Premium Field ID</label>
                    <input type="text" value={settingsData.ghl_premium_field_id} onChange={e => setSettingsData({ ...settingsData, ghl_premium_field_id: e.target.value })} className="w-full px-4 py-3 bg-white border border-slate-300 rounded-lg text-slate-800 focus:border-blue-500 outline-none transition text-sm" />
                  </div>
                  <div>
                    <label className="block text-sm font-medium text-slate-600 mb-1">Advance Status Field ID</label>
                    <input type="text" value={settingsData.ghl_advance_status_field_id} onChange={e => setSettingsData({ ...settingsData, ghl_advance_status_field_id: e.target.value })} className="w-full px-4 py-3 bg-white border border-slate-300 rounded-lg text-slate-800 focus:border-blue-500 outline-none transition text-sm" />
                  </div>
                  <div>
                    <label className="block text-sm font-medium text-slate-600 mb-1">Paid to Agent Field ID</label>
                    <input type="text" value={settingsData.ghl_paid_to_agent_field_id || ''} onChange={e => setSettingsData({ ...settingsData, ghl_paid_to_agent_field_id: e.target.value })} className="w-full px-4 py-3 bg-white border border-slate-300 rounded-lg text-slate-800 focus:border-blue-500 outline-none transition text-sm" />
                  </div>
                  <div className="sm:col-span-2 pt-4 border-t border-slate-200">
                    <h4 className="text-sm font-semibold text-rose-600 mb-3">CallTools Dialer</h4>
                  </div>
                  <div className="sm:col-span-2">
                    <label className="block text-sm font-medium text-slate-600 mb-1">CallTools API Key</label>
                    <input type="password" value={settingsData.calltools_api_key || ''} onChange={e => setSettingsData({ ...settingsData, calltools_api_key: e.target.value })} className="w-full px-4 py-3 bg-white border border-slate-300 rounded-lg text-slate-800 focus:border-blue-500 outline-none transition text-sm" placeholder="Token ..." />
                  </div>
                  <div>
                    <label className="block text-sm font-medium text-slate-600 mb-1">CallTools Team ID</label>
                    <input type="text" value={settingsData.calltools_team_id || ''} onChange={e => setSettingsData({ ...settingsData, calltools_team_id: e.target.value })} className="w-full px-4 py-3 bg-white border border-slate-300 rounded-lg text-slate-800 focus:border-blue-500 outline-none transition text-sm" placeholder="e.g. 264" />
                  </div>
                </div>
                <button onClick={handleSaveSettings} disabled={loading} className="flex items-center gap-2 px-6 py-3 bg-blue-600 hover:bg-blue-700 text-white font-semibold rounded-lg transition-all disabled:opacity-50 shadow-sm mt-4">
                  {loading ? <RotateCw className="w-4 h-4 animate-spin" /> : <Save className="w-4 h-4" />}
                  {loading ? 'Saving...' : 'Save Settings'}
                </button>
              </div>
            </div>
          )}

          {/* ===== MY DEALS TAB (Agent) — Bonus Week View ===== */}
          {currentTab === 'deals' && !isAdmin && (
            <div className="space-y-6">
              {/* Week Selector */}
              <div className="flex items-center gap-4 flex-wrap">
                <label className="text-slate-600 text-sm font-medium">Bonus Week</label>
                {bonusWeeksLoading ? (
                  <div className="flex items-center gap-2 text-slate-500 text-sm"><RefreshCw className="w-4 h-4 text-blue-600 animate-spin" /> Loading weeks...</div>
                ) : (
                  <select value={selectedWeek} onChange={e => setSelectedWeek(e.target.value)} className="px-4 py-2 bg-white border border-slate-300 rounded-lg text-slate-800 focus:border-blue-500 outline-none transition min-w-[280px]">
                    {bonusWeeks.length === 0 && <option value="">No bonus weeks found</option>}
                    {bonusWeeks.map(w => <option key={w.week_start} value={w.week_start}>{w.label}</option>)}
                  </select>
                )}
                {weekLoading && !bonusWeeksLoading && <RefreshCw className="w-4 h-4 text-blue-600 animate-spin" />}
              </div>

              {/* Billable Hours Bubble */}
              {billableHours && billableHours.billable_hours > 0 && (
                <div className="bg-white border border-slate-200 rounded-2xl shadow-sm p-6 flex items-center gap-6">
                  <div className="flex-shrink-0 w-16 h-16 rounded-full bg-blue-600 flex items-center justify-center shadow-lg shadow-blue-200">
                    <Clock className="w-8 h-8 text-white" />
                  </div>
                  <div className="flex-1">
                    <div className="text-slate-500 text-sm mb-1">Billable Hours This Week</div>
                    <div className="text-4xl font-bold text-slate-800">{billableHours.billable_hours}h</div>
                  </div>
                  <div className="hidden sm:flex gap-4 text-center">
                    <div>
                      <div className="text-lg font-semibold text-slate-800">{billableHours.available_hours}h</div>
                      <div className="text-slate-400 text-xs">Available</div>
                    </div>
                    <div>
                      <div className="text-lg font-semibold text-slate-800">{billableHours.on_call_hours}h</div>
                      <div className="text-slate-400 text-xs">On Call</div>
                    </div>
                    <div>
                      <div className="text-lg font-semibold text-slate-800">{billableHours.post_call_billable_hours}h</div>
                      <div className="text-slate-400 text-xs">Post Call</div>
                    </div>
                  </div>
                </div>
              )}

              {/* Summary Cards */}
              {weekDeals && (
                <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
                  <div className="bg-white border border-slate-200 rounded-xl shadow-sm p-5">
                    <div className="text-slate-500 text-sm mb-1">Submitted This Week</div>
                    <div className="text-3xl font-bold text-slate-800">{weekDeals.submitted_count}</div>
                    <div className="text-blue-600 text-xs mt-1">{formatCurrency(weekDeals.submitted_premium)} premium</div>
                  </div>
                  <div className="bg-white border border-slate-200 rounded-xl shadow-sm p-5">
                    <div className="text-slate-500 text-sm mb-1">Payable This Week</div>
                    <div className="text-3xl font-bold text-slate-800">{weekDeals.payable_count}</div>
                    <div className="text-emerald-600 text-xs mt-1">{formatCurrency(weekDeals.payable_premium)} premium</div>
                  </div>
                  <div className="bg-white border border-slate-200 rounded-xl shadow-sm p-5">
                    <div className="text-slate-500 text-sm mb-1">Total Deals</div>
                    <div className="text-3xl font-bold text-slate-800">{weekDeals.all_deals_count}</div>
                    <div className="text-purple-600 text-xs mt-1">across all weeks</div>
                  </div>
                </div>
              )}

              {/* Submitted Deals Table */}
              <div className="bg-white border border-slate-200 rounded-xl shadow-sm overflow-hidden">
                <div className="px-6 py-4 border-b border-slate-200 flex items-center justify-between">
                  <h2 className="text-slate-800 text-lg font-semibold flex items-center gap-2"><FileText className="w-5 h-5 text-blue-600" /> Submitted This Week</h2>
                  <span className="text-slate-500 text-sm">{weekDeals?.submitted_count || 0} deals</span>
                </div>
                <div className="overflow-x-auto">
                  <table className="w-full">
                    <thead><tr className="border-b border-slate-200">
                      <th className="text-left px-6 py-3 text-xs font-medium text-slate-500 uppercase tracking-wider">Customer</th>
                      <th className="text-left px-6 py-3 text-xs font-medium text-slate-500 uppercase tracking-wider">Date Submitted</th>
                      <th className="text-left px-6 py-3 text-xs font-medium text-slate-500 uppercase tracking-wider">Policy #</th>
                      <th className="text-left px-6 py-3 text-xs font-medium text-slate-500 uppercase tracking-wider">Type</th>
                      <th className="text-left px-6 py-3 text-xs font-medium text-slate-500 uppercase tracking-wider">Effective Date</th>
                      <th className="text-left px-6 py-3 text-xs font-medium text-slate-500 uppercase tracking-wider">Draft Date</th>
                      <th className="text-left px-6 py-3 text-xs font-medium text-slate-500 uppercase tracking-wider">Premium</th>
                    </tr></thead>
                    <tbody className="divide-y divide-slate-100">
                      {weekDeals?.submitted_deals.map((deal, i) => (
                        <tr key={deal.id || i} className="hover:bg-slate-50 transition-colors">
                          <td className="px-6 py-3 text-sm text-slate-800">{deal.contact_name}</td>
                          <td className="px-6 py-3 text-sm text-slate-500">{deal.date_added ? fmtDate(deal.date_added) : '—'}</td>
                          <td className="px-6 py-3 text-sm text-slate-600">{deal.policy_number || '—'}</td>
                          <td className="px-6 py-3 text-sm text-slate-600">{deal.plan_name || '—'}</td>
                          <td className="px-6 py-3 text-sm text-slate-500">{deal.effective_date ? fmtDate(deal.effective_date) : '—'}</td>
                          <td className="px-6 py-3 text-sm text-slate-500">{deal.premium_draft_date ? fmtDate(deal.premium_draft_date) : '—'}</td>
                          <td className="px-6 py-3 text-sm font-semibold text-blue-600">{formatCurrency(deal.premium)}</td>
                        </tr>
                      ))}
                      {(!weekDeals || weekDeals.submitted_deals.length === 0) && (
                        <tr><td colSpan={7} className="px-6 py-8 text-center text-slate-400">No deals submitted this week</td></tr>
                      )}
                    </tbody>
                  </table>
                </div>
              </div>

              {/* Payable Deals Table */}
              <div className="bg-white border border-slate-200 rounded-xl shadow-sm overflow-hidden">
                <div className="px-6 py-4 border-b border-slate-200 flex items-center justify-between">
                  <h2 className="text-slate-800 text-lg font-semibold flex items-center gap-2"><DollarSign className="w-5 h-5 text-emerald-600" /> Payable This Week</h2>
                  <span className="text-slate-500 text-sm">{weekDeals?.payable_count || 0} deals</span>
                </div>
                <div className="overflow-x-auto">
                  <table className="w-full">
                    <thead><tr className="border-b border-slate-200">
                      <th className="text-left px-6 py-3 text-xs font-medium text-slate-500 uppercase tracking-wider">Customer</th>
                      <th className="text-left px-6 py-3 text-xs font-medium text-slate-500 uppercase tracking-wider">Draft Date</th>
                      <th className="text-left px-6 py-3 text-xs font-medium text-slate-500 uppercase tracking-wider">Policy #</th>
                      <th className="text-left px-6 py-3 text-xs font-medium text-slate-500 uppercase tracking-wider">Type</th>
                      <th className="text-left px-6 py-3 text-xs font-medium text-slate-500 uppercase tracking-wider">Effective Date</th>
                      <th className="text-left px-6 py-3 text-xs font-medium text-slate-500 uppercase tracking-wider">Date Submitted</th>
                      <th className="text-left px-6 py-3 text-xs font-medium text-slate-500 uppercase tracking-wider">Premium</th>
                      <th className="text-left px-6 py-3 text-xs font-medium text-slate-500 uppercase tracking-wider">Status</th>
                    </tr></thead>
                    <tbody className="divide-y divide-slate-100">
                      {weekDeals?.payable_deals.map((deal, i) => (
                        <tr key={deal.id || i} className="hover:bg-slate-50 transition-colors">
                          <td className="px-6 py-3 text-sm text-slate-800">{deal.contact_name}</td>
                          <td className="px-6 py-3 text-sm text-slate-500">{deal.premium_draft_date ? fmtDate(deal.premium_draft_date) : '—'}</td>
                          <td className="px-6 py-3 text-sm text-slate-600">{deal.policy_number || '—'}</td>
                          <td className="px-6 py-3 text-sm text-slate-600">{deal.plan_name || '—'}</td>
                          <td className="px-6 py-3 text-sm text-slate-500">{deal.effective_date ? fmtDate(deal.effective_date) : '—'}</td>
                          <td className="px-6 py-3 text-sm text-slate-500">{deal.date_added ? fmtDate(deal.date_added) : '—'}</td>
                          <td className="px-6 py-3 text-sm font-semibold text-emerald-600">{formatCurrency(deal.premium)}</td>
                          <td className="px-6 py-3">
                            <span className="text-xs px-2 py-1 rounded-full font-medium bg-emerald-100 text-emerald-700">{deal.status}</span>
                          </td>
                        </tr>
                      ))}
                      {(!weekDeals || weekDeals.payable_deals.length === 0) && (
                        <tr><td colSpan={8} className="px-6 py-8 text-center text-slate-400">No payable deals this week</td></tr>
                      )}
                    </tbody>
                  </table>
                </div>
              </div>
              <div className="bg-white border border-red-200 rounded-xl shadow-sm overflow-hidden">
                <div className="px-6 py-4 border-b border-red-100 flex items-center justify-between">
                  <h2 className="text-slate-800 text-lg font-semibold flex items-center gap-2"><AlertTriangle className="w-5 h-5 text-red-600" /> Cancels / Failed</h2>
                  <span className="text-slate-500 text-sm">{weekDeals?.failed_count || 0} deals</span>
                </div>
                <div className="overflow-x-auto">
                  <table className="w-full">
                    <thead><tr className="border-b border-red-100">
                      <th className="text-left px-6 py-3 text-xs font-medium text-slate-500 uppercase tracking-wider">Customer</th>
                      <th className="text-left px-6 py-3 text-xs font-medium text-slate-500 uppercase tracking-wider">Date Submitted</th>
                      <th className="text-left px-6 py-3 text-xs font-medium text-slate-500 uppercase tracking-wider">Policy #</th>
                      <th className="text-left px-6 py-3 text-xs font-medium text-slate-500 uppercase tracking-wider">Type</th>
                      <th className="text-left px-6 py-3 text-xs font-medium text-slate-500 uppercase tracking-wider">Effective Date</th>
                      <th className="text-left px-6 py-3 text-xs font-medium text-slate-500 uppercase tracking-wider">Draft Date</th>
                      <th className="text-left px-6 py-3 text-xs font-medium text-slate-500 uppercase tracking-wider">Premium</th>
                      <th className="text-left px-6 py-3 text-xs font-medium text-slate-500 uppercase tracking-wider">Status</th>
                      <th className="text-left px-6 py-3 text-xs font-medium text-slate-500 uppercase tracking-wider">Reason</th>
                    </tr></thead>
                    <tbody className="divide-y divide-red-50">
                      {weekDeals?.failed_deals.map((deal, i) => (
                        <tr key={deal.id || i} className="hover:bg-red-50 transition-colors">
                          <td className="px-6 py-3 text-sm text-slate-800">{deal.contact_name}</td>
                          <td className="px-6 py-3 text-sm text-slate-500">{deal.date_added ? fmtDate(deal.date_added) : '—'}</td>
                          <td className="px-6 py-3 text-sm text-slate-600">{deal.policy_number || '—'}</td>
                          <td className="px-6 py-3 text-sm text-slate-600">{deal.plan_name || '—'}</td>
                          <td className="px-6 py-3 text-sm text-slate-500">{deal.effective_date ? fmtDate(deal.effective_date) : '—'}</td>
                          <td className="px-6 py-3 text-sm text-slate-500">{deal.premium_draft_date ? fmtDate(deal.premium_draft_date) : '—'}</td>
                          <td className="px-6 py-3 text-sm font-semibold text-red-600">{formatCurrency(deal.premium)}</td>
                          <td className="px-6 py-3"><span className={`text-xs px-2 py-1 rounded-full font-medium ${deal.status === 'Chargeback' ? 'bg-red-100 text-red-700' : 'bg-amber-100 text-amber-700'}`}>{deal.status}</span></td>
                          <td className="px-6 py-3 text-sm text-slate-500">{deal.reason || '—'}</td>
                        </tr>
                      ))}
                      {(!weekDeals || weekDeals.failed_deals.length === 0) && (
                        <tr><td colSpan={9} className="px-6 py-8 text-center text-slate-400">No cancelled or failed deals this week</td></tr>
                      )}
                    </tbody>
                  </table>
                </div>
              </div>
            </div>
          )}


        </div>
      </main>
    </div>
  )
}

function LeaderboardPage() {
  const { slug } = useParams<{ slug: string }>()
  const navigate = useNavigate()
  const [data, setData] = useState<LeaderboardResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [showLogin, setShowLogin] = useState(false)
  const [loginRole, setLoginRole] = useState<'agent' | 'admin'>('agent')
  const [activeTab, setActiveTab] = useState<'leaders' | 'breakdown'>('leaders')
  const [breakdownPeriod, setBreakdownPeriod] = useState<'daily' | 'weekly' | 'monthly'>('daily')
  const [darkMode, setDarkMode] = useState(() => localStorage.getItem('theme') !== 'light')
  const { user } = useAuth()
  const fetchRef = useRef(false)

  const fetchLeaderboard = useCallback(async () => {
    if (fetchRef.current) return
    fetchRef.current = true
    try {
      const url = slug ? API_URL + '/leaderboard/' + slug : API_URL + '/leaderboard'
      const res = await fetch(url)
      if (res.ok) { setData(await res.json()); setError('') }
      else setError('Failed to load leaderboard')
    } catch { setError('Network error') }
    setLoading(false)
    fetchRef.current = false
  }, [slug])

  useEffect(() => { fetchLeaderboard() }, [fetchLeaderboard])

  useEffect(() => {
    const id = setInterval(fetchLeaderboard, 60000)
    return () => clearInterval(id)
  }, [fetchLeaderboard])

  useEffect(() => { localStorage.setItem('theme', darkMode ? 'dark' : 'light') }, [darkMode])

  const d = darkMode
  const bg = d ? 'bg-zinc-900' : 'bg-gray-200'
  const headerBg = d ? 'bg-zinc-900/80 border-zinc-700' : 'bg-white border-gray-300 shadow-sm'
  const cardBg = d ? 'bg-zinc-800/80 border-zinc-700' : 'bg-white border-gray-300 shadow-md'
  const textPrimary = d ? 'text-white' : 'text-gray-900'
  const textSecondary = d ? 'text-zinc-400' : 'text-gray-600'
  const textMuted = d ? 'text-zinc-500' : 'text-gray-500'
  const tabActive = d ? 'bg-gradient-to-r from-teal-500 to-cyan-600 text-white shadow-lg shadow-teal-500/20' : 'bg-gradient-to-r from-teal-600 to-cyan-700 text-white shadow-md'
  const tabInactive = d ? 'bg-zinc-800 text-zinc-400 hover:text-white border border-zinc-700' : 'bg-white text-gray-600 hover:text-gray-900 border border-gray-300 hover:border-teal-400'
  const barBg = d ? 'bg-zinc-700' : 'bg-gray-300'
  const leaderItemBg = d ? 'bg-zinc-800/80 border-zinc-600 hover:border-purple-400/40' : 'bg-white border-gray-300 hover:border-teal-400 shadow-sm'
  const leaderItemBgSub = d ? 'bg-zinc-800/50 hover:bg-zinc-800/70' : 'bg-gray-100 hover:bg-gray-200 border border-gray-300'
  const breakdownItemBg = d ? 'bg-zinc-700/60' : 'bg-gray-100 border border-gray-300'

  if (loading && !data) return (
    <div className={`min-h-screen ${bg} flex items-center justify-center`}>
      <div className="text-center"><RefreshCw className="w-12 h-12 text-teal-400 animate-spin mx-auto mb-4" /><p className={`${textSecondary} text-lg`}>Loading leaderboard...</p></div>
    </div>
  )

  if (error && !data) return (
    <div className={`min-h-screen ${bg} flex items-center justify-center`}>
      <div className="text-center"><AlertCircle className="w-12 h-12 text-red-400 mx-auto mb-4" /><p className="text-red-400 text-lg">{error}</p><button onClick={fetchLeaderboard} className="mt-4 px-4 py-2 bg-teal-500/20 text-teal-400 rounded-lg hover:bg-teal-500/30 transition">Retry</button></div>
    </div>
  )

  if (!data) return null

  const dailyData = data.daily
  const maxPremium = Math.max(...(dailyData.leaders || []).map(l => l.premium), 1)
  const todayDate = new Date().toLocaleDateString('en-US', { weekday: 'long', year: 'numeric', month: 'long', day: 'numeric' })
  const breakdown = breakdownPeriod === 'weekly' ? data.weekly_breakdown : breakdownPeriod === 'monthly' ? data.monthly_breakdown : data.daily_breakdown
  const summarySource = activeTab === 'breakdown'
    ? (breakdownPeriod === 'weekly' ? data.weekly : breakdownPeriod === 'monthly' ? data.monthly : data.daily)
    : data.daily
  const avgPremium = summarySource.total_deals > 0 ? summarySource.total_premium / summarySource.total_deals : 0
  const breakdownDateLabel = breakdownPeriod === 'weekly'
    ? `${data.weekly.start_date} — ${data.weekly.end_date}`
    : breakdownPeriod === 'monthly'
      ? `${data.monthly.start_date} — ${data.monthly.end_date}`
      : todayDate

  return (
    <div className={`min-h-screen ${bg} transition-colors duration-300`}>
      {showLogin && <LoginModal onClose={() => setShowLogin(false)} role={loginRole} />}

      <header className={`${headerBg} backdrop-blur-lg border-b sticky top-0 z-40 transition-colors duration-300`}>
        <div className="max-w-7xl mx-auto px-4 sm:px-6 py-4 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="p-2 bg-gradient-to-br from-teal-500 to-cyan-600 rounded-xl shadow-lg shadow-teal-500/20"><Shield className="w-7 h-7 text-white" /></div>
            <div>
              <h1 className={`text-xl font-bold ${textPrimary}`}>{data.agency_name || 'AP Insurance Partners'}</h1>
              <p className={`${textSecondary} text-xs`}>Agent Leaderboard</p>
            </div>
          </div>
          <div className="flex items-center gap-2">
            <button onClick={() => navigate('/submit')} className={`flex items-center gap-1.5 px-3 py-2 rounded-lg font-medium text-sm transition-all ${d ? 'bg-teal-500/10 text-teal-400 hover:bg-teal-500/20' : 'bg-teal-50 text-teal-700 hover:bg-teal-100'}`} title="Submit a Deal"><FileText className="w-4 h-4" /> Submit Deal</button>
            <button onClick={() => setDarkMode(!darkMode)} className={`p-2 rounded-lg ${textSecondary} hover:text-teal-400 transition`} title={darkMode ? 'Light Mode' : 'Dark Mode'}>
              {darkMode ? <Sun className="w-5 h-5" /> : <Moon className="w-5 h-5" />}
            </button>
            <button onClick={fetchLeaderboard} className={`p-2 rounded-lg ${textSecondary} hover:text-teal-400 transition`} title="Refresh"><RefreshCw className="w-5 h-5" /></button>
            {user ? (
              <button onClick={() => navigate('/portal')} className="flex items-center gap-2 px-4 py-2 bg-gradient-to-r from-teal-500 to-cyan-600 text-white rounded-lg font-medium text-sm hover:from-teal-600 hover:to-cyan-700 transition-all shadow-lg shadow-teal-500/20"><LayoutDashboard className="w-4 h-4" /> Portal</button>
            ) : (
              <div className="flex items-center gap-2">
                <button onClick={() => { setLoginRole('agent'); setShowLogin(true) }} className={`flex items-center gap-2 px-4 py-2 rounded-lg font-medium text-sm transition-all shadow-lg ${d ? 'bg-gradient-to-r from-teal-500 to-cyan-600 text-white hover:from-teal-600 hover:to-cyan-700 shadow-teal-500/20' : 'bg-gradient-to-r from-teal-600 to-cyan-700 text-white hover:from-teal-700 hover:to-cyan-800 shadow-teal-600/20'}`}><LogIn className="w-4 h-4" /> Agent Login</button>
                <button onClick={() => { setLoginRole('admin'); setShowLogin(true) }} className={`flex items-center gap-2 px-4 py-2 rounded-lg font-medium text-sm transition-all shadow-lg ${d ? 'bg-gradient-to-r from-purple-500 to-violet-600 text-white hover:from-purple-600 hover:to-violet-700 shadow-purple-500/20' : 'bg-gradient-to-r from-purple-600 to-violet-700 text-white hover:from-purple-700 hover:to-violet-800 shadow-purple-600/20'}`}><Shield className="w-4 h-4" /> Admin Login</button>
              </div>
            )}
          </div>
        </div>
      </header>

      <div className="max-w-7xl mx-auto px-4 sm:px-6 py-8">
        <div className="flex gap-2 mb-8">
          <button onClick={() => setActiveTab('leaders')} className={`px-5 py-2.5 rounded-xl text-sm font-semibold transition-all ${activeTab === 'leaders' ? tabActive : tabInactive}`}>Today&apos;s Leaders</button>
          <button onClick={() => setActiveTab('breakdown')} className={`px-5 py-2.5 rounded-xl text-sm font-semibold transition-all flex items-center gap-2 ${activeTab === 'breakdown' ? tabActive : tabInactive}`}><BarChart3 className="w-4 h-4" /> Deal Breakdown</button>
        </div>

        <div className="grid grid-cols-1 sm:grid-cols-3 gap-4 mb-8">
          <div className={`${d ? 'bg-gradient-to-br from-teal-500/15 to-cyan-500/10 border-teal-500/30' : 'bg-gradient-to-br from-teal-100 to-cyan-100 border-teal-300'} border rounded-xl p-5`}>
            <div className="flex items-center gap-3 mb-2"><Trophy className="w-6 h-6 text-teal-500" /><span className={`${textSecondary} text-sm`}>Total Deals</span></div>
            <div className={`text-3xl font-bold ${textPrimary}`}>{summarySource.total_deals}</div>
          </div>
          <div className={`${d ? 'bg-gradient-to-br from-purple-500/20 to-violet-500/10 border-zinc-600' : 'bg-gradient-to-br from-purple-100 to-violet-100 border-purple-300'} border rounded-xl p-5`}>
            <div className="flex items-center gap-3 mb-2"><DollarSign className="w-6 h-6 text-purple-500" /><span className={`${textSecondary} text-sm`}>Total Premium</span></div>
            <div className={`text-3xl font-bold ${textPrimary}`}>{formatCurrency(summarySource.total_premium)}</div>
          </div>
          <div className={`${d ? 'bg-gradient-to-br from-rose-500/15 to-pink-500/10 border-rose-500/30' : 'bg-gradient-to-br from-rose-100 to-pink-100 border-rose-300'} border rounded-xl p-5`}>
            <div className="flex items-center gap-3 mb-2"><TrendingUp className="w-6 h-6 text-rose-500" /><span className={`${textSecondary} text-sm`}>Average Premium</span></div>
            <div className={`text-3xl font-bold ${textPrimary}`}>{formatCurrency(avgPremium)}</div>
          </div>
        </div>

        {activeTab === 'leaders' && (
          <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
            <div className="lg:col-span-2">
              <div className={`${cardBg} border rounded-xl p-6 transition-colors duration-300`}>
                <div className="flex items-center gap-2 mb-6">
                  <Trophy className="w-6 h-6 text-yellow-400" />
                  <h2 className={`text-xl font-bold ${textPrimary}`}>Today&apos;s Leaders</h2>
                  <span className={`${textSecondary} text-sm ml-auto`}>{todayDate}</span>
                </div>
                <div className="space-y-3">
                  {dailyData.leaders?.length === 0 ? (
                    <div className="text-center py-12"><Trophy className={`w-16 h-16 ${textMuted} mx-auto mb-4`} /><p className={`${textSecondary} text-lg`}>No deals yet today</p><p className={`${textMuted} text-sm mt-1`}>Be the first to close a deal!</p></div>
                  ) : dailyData.leaders?.map((entry, index) => {
                    const progress = maxPremium > 0 ? (entry.premium / maxPremium) * 100 : 0
                    const isTopThree = index < 3
                    const rank = index + 1
                    return (
                      <div key={entry.name + '-' + index} className={`relative flex items-center gap-4 p-4 rounded-xl transition-all duration-300 ${isTopThree ? `${leaderItemBg} border` : leaderItemBgSub} ${rank === 1 ? 'ring-2 ring-yellow-400/30 shadow-lg shadow-yellow-400/10' : ''}`}>
                        <div className={`flex items-center justify-center w-10 h-10 rounded-full text-sm font-bold ${getRankBadge(rank)}`}>
                          {getRankIcon(rank) || `#${rank}`}
                        </div>
                        <div className={`w-12 h-12 rounded-full flex items-center justify-center text-white font-bold text-lg bg-gradient-to-br ${getAvatarColor(entry.name)} shadow-lg`}>
                          {getInitials(entry.name)}
                        </div>
                        <div className="flex-1 min-w-0">
                          <div className="flex items-center gap-2">
                            <span className={`font-semibold truncate ${isTopThree ? `${textPrimary} text-lg` : d ? 'text-slate-200' : 'text-gray-700'}`}>{entry.name}</span>
                            {getStreakEmoji(entry.deals)}
                          </div>
                          <div className="mt-2">
                            <div className={`w-full ${barBg} rounded-full h-2`}>
                              <div className={`h-2 rounded-full transition-all duration-500 ${rank === 1 ? 'bg-gradient-to-r from-yellow-400 to-yellow-500' : 'bg-gradient-to-r from-teal-400 to-cyan-500'}`} style={{ width: `${progress}%` }} />
                            </div>
                          </div>
                        </div>
                        <div className="text-right shrink-0">
                          <div className={`text-2xl font-bold ${isTopThree ? textPrimary : d ? 'text-slate-200' : 'text-gray-700'}`}>{entry.deals}</div>
                          <div className={`text-xs ${textSecondary}`}>deals</div>
                          {entry.premium > 0 && <div className="text-sm font-semibold text-teal-500 mt-0.5">{formatCurrency(entry.premium)}</div>}
                        </div>
                      </div>
                    )
                  })}
                </div>
              </div>
            </div>

            <div className="space-y-6">
              {[
                { title: 'This Week', icon: <Clock className="w-4 h-4 text-cyan-400" />, accentBg: d ? 'bg-cyan-500/20' : 'bg-cyan-100', listData: data.weekly },
                { title: 'This Month', icon: <Star className="w-4 h-4 text-purple-400" />, accentBg: d ? 'bg-purple-500/20' : 'bg-purple-100', listData: data.monthly },
              ].map(side => (
                <div key={side.title} className={`${cardBg} border rounded-xl overflow-hidden transition-colors duration-300`}>
                  <div className={`px-5 py-4 border-b ${d ? 'border-zinc-700' : 'border-gray-300'}`}>
                    <div className="flex items-center justify-between">
                      <div className="flex items-center gap-2">
                        <div className={`p-2 rounded-lg ${side.accentBg}`}>{side.icon}</div>
                        <div>
                          <h3 className={`${textPrimary} text-lg font-semibold`}>{side.title}</h3>
                          <p className={`text-xs ${textSecondary}`}>{side.listData.start_date} — {side.listData.end_date}</p>
                        </div>
                      </div>
                      <div className="text-right">
                        <div className={`text-lg font-bold ${textPrimary}`}>{side.listData.total_deals}</div>
                        <div className={`text-xs ${textSecondary}`}>deals</div>
                        {side.listData.total_premium > 0 && <div className="text-xs font-semibold text-teal-500">{formatCurrency(side.listData.total_premium)}</div>}
                      </div>
                    </div>
                  </div>
                  <div className="p-4 max-h-64 overflow-y-auto">
                    <div className="space-y-2">
                      {(side.listData.leaders || []).length === 0 ? (
                        <div className={`text-center py-8 ${textSecondary}`}><Trophy className="w-12 h-12 mx-auto mb-2 opacity-30" /><p>No deals yet</p></div>
                      ) : (side.listData.leaders || []).map((entry, index) => (
                        <div key={`${side.title}-${entry.name}-${index}`} className={`flex items-center gap-3 p-3 rounded-lg ${d ? 'bg-zinc-700/50 hover:bg-zinc-700/80' : 'bg-gray-100 hover:bg-gray-200'} transition-colors`}>
                          <div className={`w-7 h-7 rounded-full flex items-center justify-center text-xs font-bold ${getRankBadge(index + 1)}`}>{index + 1 <= 3 ? getRankIcon(index + 1) || (index + 1) : index + 1}</div>
                          <div className={`w-9 h-9 rounded-full flex items-center justify-center text-white font-semibold text-sm bg-gradient-to-br ${getAvatarColor(entry.name)}`}>{getInitials(entry.name)}</div>
                          <div className="flex-1 min-w-0"><span className={`${d ? 'text-slate-200' : 'text-gray-700'} font-medium truncate block`}>{entry.name}</span></div>
                          <div className="flex items-center gap-2 shrink-0">
                            {getStreakEmoji(entry.deals)}
                            <div className="text-right">
                              <span className={`${textPrimary} font-bold`}>{entry.deals}</span>
                              {entry.premium > 0 && <div className="text-xs text-teal-500 font-semibold">{formatCurrency(entry.premium)}</div>}
                            </div>
                          </div>
                        </div>
                      ))}
                    </div>
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}

        {activeTab === 'breakdown' && breakdown && (
          <div>
            <div className="flex gap-2 mb-6">
              {(['daily', 'weekly', 'monthly'] as const).map(p => (
                <button key={p} onClick={() => setBreakdownPeriod(p)} className={`px-4 py-2 rounded-lg text-sm font-semibold transition-all ${breakdownPeriod === p ? (d ? 'bg-purple-500/30 text-purple-300 border border-purple-400/40' : 'bg-purple-100 text-purple-700 border border-purple-300') : (d ? 'bg-zinc-800 text-zinc-400 hover:text-white border border-zinc-700' : 'bg-white text-gray-600 hover:text-gray-800 border border-gray-300')}`}>
                  {p === 'daily' ? 'Today' : p === 'weekly' ? 'This Week' : 'This Month'}
                </button>
              ))}
            </div>
            <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
            <div className={`${cardBg} border rounded-xl p-6 transition-colors duration-300`}>
              <div className="flex items-center gap-2 mb-6">
                <MapPin className="w-6 h-6 text-teal-500" />
                <h2 className={`text-xl font-bold ${textPrimary}`}>By State</h2>
                <span className={`${textSecondary} text-sm ml-auto`}>{breakdownDateLabel}</span>
              </div>
              {breakdown.states.length === 0 ? (
                <div className="text-center py-12"><MapPin className={`w-16 h-16 ${textMuted} mx-auto mb-4`} /><p className={`${textSecondary}`}>No data yet</p></div>
              ) : (
                <div className="space-y-3">
                  {breakdown.states.map((item, i) => {
                    const maxCount = breakdown.states[0]?.count || 1
                    return (
                      <div key={item.label + i} className={`${breakdownItemBg} rounded-xl p-4 transition-colors`}>
                        <div className="flex items-center justify-between mb-2">
                          <span className={`font-semibold ${textPrimary}`}>{item.label}</span>
                          <div className="flex items-center gap-3">
                            <span className={`text-sm font-bold ${textPrimary}`}>{item.count} deals</span>
                            <span className="text-sm font-semibold text-teal-500">{formatCurrency(item.premium)}</span>
                          </div>
                        </div>
                        <div className={`w-full ${barBg} rounded-full h-2`}>
                          <div className="h-2 rounded-full bg-gradient-to-r from-teal-400 to-cyan-500 transition-all duration-500" style={{ width: `${(item.count / maxCount) * 100}%` }} />
                        </div>
                      </div>
                    )
                  })}
                </div>
              )}
            </div>
            <div className={`${cardBg} border rounded-xl p-6 transition-colors duration-300`}>
              <div className="flex items-center gap-2 mb-6">
                <Briefcase className="w-6 h-6 text-purple-500" />
                <h2 className={`text-xl font-bold ${textPrimary}`}>By Plan Type</h2>
                <span className={`${textSecondary} text-sm ml-auto`}>{breakdownDateLabel}</span>
              </div>
              {breakdown.plan_types.length === 0 ? (
                <div className="text-center py-12"><Briefcase className={`w-16 h-16 ${textMuted} mx-auto mb-4`} /><p className={`${textSecondary}`}>No data yet</p></div>
              ) : (
                <div className="space-y-3">
                  {breakdown.plan_types.map((item, i) => {
                    const maxCount = breakdown.plan_types[0]?.count || 1
                    const colors = ['from-purple-400 to-violet-500', 'from-teal-400 to-cyan-500', 'from-rose-400 to-pink-500', 'from-amber-400 to-orange-500', 'from-emerald-400 to-green-500']
                    return (
                      <div key={item.label + i} className={`${breakdownItemBg} rounded-xl p-4 transition-colors`}>
                        <div className="flex items-center justify-between mb-2">
                          <span className={`font-semibold ${textPrimary}`}>{item.label}</span>
                          <div className="flex items-center gap-3">
                            <span className={`text-sm font-bold ${textPrimary}`}>{item.count} deals</span>
                            <span className="text-sm font-semibold text-purple-500">{formatCurrency(item.premium)}</span>
                          </div>
                        </div>
                        <div className={`w-full ${barBg} rounded-full h-2`}>
                          <div className={`h-2 rounded-full bg-gradient-to-r ${colors[i % colors.length]} transition-all duration-500`} style={{ width: `${(item.count / maxCount) * 100}%` }} />
                        </div>
                      </div>
                    )
                  })}
                </div>
              )}
            </div>
          </div>
          </div>
        )}

        {activeTab === 'breakdown' && !breakdown && (
          <div className={`${cardBg} border rounded-xl p-12 text-center transition-colors duration-300`}>
            <BarChart3 className={`w-16 h-16 ${textMuted} mx-auto mb-4`} />
            <p className={`${textSecondary} text-lg`}>No breakdown data available</p>
          </div>
        )}

        <div className={`text-center py-6 mt-8 border-t ${d ? 'border-zinc-700' : 'border-gray-300'}`}>
          <p className={`${textMuted} text-sm`}>Last updated: {data.last_sync ? new Date(data.last_sync).toLocaleString() : 'Unknown'}</p>
          <p className={`${d ? 'text-slate-600' : 'text-gray-300'} text-xs mt-1`}>AP Insurance Partners Portal</p>
        </div>
      </div>
    </div>
  )
}

function App() {
  return (
    <BrowserRouter>
      <AuthProvider>
        <Routes>
          <Route path="/" element={<LeaderboardPage />} />
          <Route path="/portal" element={<Portal />} />
          <Route path="/submit" element={<DealSubmission agencyName="AP Insurance Partners" agencySlug="ap-insurance" />} />
          <Route path="/:slug" element={<LeaderboardPage />} />
        </Routes>
      </AuthProvider>
    </BrowserRouter>
  )
}

export default App

/* UX animation keyframes — injected via style tag */
const styleSheet = document.createElement('style')
styleSheet.textContent = `
  @keyframes slideIn {
    from { transform: translateX(100%); opacity: 0; }
    to { transform: translateX(0); opacity: 1; }
  }
  @keyframes slideInRight {
    from { transform: translateX(100%); }
    to { transform: translateX(0); }
  }
  @keyframes fadeIn {
    from { opacity: 0; transform: translateY(8px); }
    to { opacity: 1; transform: translateY(0); }
  }
`
document.head.appendChild(styleSheet)
