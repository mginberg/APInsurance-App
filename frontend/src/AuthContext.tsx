import { createContext, useContext, useState, useEffect, type ReactNode } from 'react'

const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:8001'

interface UserInfo {
  id: string
  email: string
  role: string
  agent_name: string
  agency_id: string
}

interface AgencyInfo {
  id: string
  code: string
  name: string
  slug: string
}

interface AuthState {
  token: string | null
  user: UserInfo | null
  agency: AgencyInfo | null
}

interface AuthContextType extends AuthState {
  login: (email: string, password: string) => Promise<{ success: boolean; error?: string; must_change_password?: boolean }>
  logout: () => void
  isAuthenticated: boolean
  mustChangePassword: boolean
  clearMustChangePassword: () => void
}

const AuthContext = createContext<AuthContextType | null>(null)

export function AuthProvider({ children }: { children: ReactNode }) {
  const [auth, setAuth] = useState<AuthState>(() => {
    const saved = localStorage.getItem('ap_insurance_auth')
    if (saved) {
      try {
        return JSON.parse(saved)
      } catch {
        return { token: null, user: null, agency: null }
      }
    }
    return { token: null, user: null, agency: null }
  })
  const [mustChangePassword, setMustChangePassword] = useState(false)

  useEffect(() => {
    if (auth.token) {
      localStorage.setItem('ap_insurance_auth', JSON.stringify(auth))
    } else {
      localStorage.removeItem('ap_insurance_auth')
    }
  }, [auth])

  const login = async (email: string, password: string) => {
    try {
      const res = await fetch(`${API_URL}/api/auth/login`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email, password }),
      })
      if (!res.ok) {
        const err = await res.json()
        return { success: false, error: err.detail || 'Login failed' }
      }
      const data = await res.json()
      setAuth({ token: data.token, user: data.user, agency: data.agency })
      if (data.must_change_password) {
        setMustChangePassword(true)
      }
      return { success: true, must_change_password: data.must_change_password }
    } catch {
      return { success: false, error: 'Network error' }
    }
  }

  const logout = () => {
    setAuth({ token: null, user: null, agency: null })
    setMustChangePassword(false)
  }

  const clearMustChangePassword = () => {
    setMustChangePassword(false)
  }

  return (
    <AuthContext.Provider value={{ ...auth, login, logout, isAuthenticated: !!auth.token, mustChangePassword, clearMustChangePassword }}>
      {children}
    </AuthContext.Provider>
  )
}

export function useAuth() {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth must be used within AuthProvider')
  return ctx
}
