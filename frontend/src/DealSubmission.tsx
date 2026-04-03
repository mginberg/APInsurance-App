import { useState, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { ArrowLeft, CheckCircle, AlertTriangle, Loader2 } from 'lucide-react'

const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:8001'

const STATES = ["AL","AK","AZ","AR","CA","CO","CT","DE","FL","GA","HI","ID","IL","IN","IA","KS","KY","LA","ME","MD","MA","MI","MN","MS","MO","MT","NE","NV","NH","NJ","NM","NY","NC","ND","OH","OK","OR","PA","RI","SC","SD","TN","TX","UT","VT","VA","WA","WV","WI","WY"]

const PLAN_TYPES = [
  "HOSPITAL INDEMNITY SHIELD",
  "GUARANTEED ISSUE HOSPITAL INDEMNITY SHIELD",
  "HOME HEALTHCARE SHIELD",
  "DENTAL SHIELD 2.0",
  "CANCER SHIELD 2.0",
  "FINAL EXPENSE SHIELD",
  "CAREGIVER SHIELD",
]

interface SubmitResult {
  success: boolean
  primaryId?: string
  addonId?: string | null
  message: string
}

export default function DealSubmission({ agencyName, agencySlug }: { agencyName: string; agencySlug: string }) {
  const navigate = useNavigate()
  const [agents, setAgents] = useState<string[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [success, setSuccess] = useState<SubmitResult | null>(null)
  const [hasAddon, setHasAddon] = useState(false)

  const [form, setForm] = useState({
    firstName: '', lastName: '', dob: '', phone: '',
    address: '', city: '', state: '', zipCode: '',
    planType: '', premium: '', policyNumber: '',
    effectiveDate: '', draftDate: '', agentName: '',
    leadId: '',
    addonPlanType: '', addonPolicyNumber: '', addonPremium: '',
  })

  useEffect(() => {
    fetch(`${API_URL}/api/deal-submission/agents/${agencySlug}`)
      .then(r => r.json())
      .then(data => setAgents(data.agents || []))
      .catch(() => setAgents([]))
  }, [agencySlug])

  const handleChange = (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) => {
    const { name, value } = e.target

    // First/Last name: letters (including accented), spaces, hyphens, apostrophes only
    if (name === 'firstName' || name === 'lastName') {
      const cleaned = value.replace(/[^\p{L}\s'-]/gu, '')
      setForm(prev => ({ ...prev, [name]: cleaned }))
      return
    }

    // Phone: digits only, max 10
    if (name === 'phone') {
      const digits = value.replace(/\D/g, '').slice(0, 10)
      setForm(prev => ({ ...prev, phone: digits }))
      return
    }

    // Premium fields: numbers and decimal only, no $ or other symbols
    if (name === 'premium' || name === 'addonPremium') {
      if (value.includes('$')) {
        setError('Do not include the $ symbol — enter the number only (e.g. 49.99).')
        setTimeout(() => setError(prev => prev === 'Do not include the $ symbol — enter the number only (e.g. 49.99).' ? '' : prev), 3000)
      }
      const cleaned = value.replace(/[^0-9.]/g, '')
      // Prevent multiple decimal points
      const parts = cleaned.split('.')
      const sanitized = parts.length > 2 ? parts[0] + '.' + parts.slice(1).join('') : cleaned
      setForm(prev => ({ ...prev, [name]: sanitized }))
      return
    }

    // ZIP code: digits only, max 5
    if (name === 'zipCode') {
      const digits = value.replace(/\D/g, '').slice(0, 5)
      setForm(prev => ({ ...prev, zipCode: digits }))
      return
    }

    setForm(prev => ({ ...prev, [name]: value }))
  }

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setError('')
    setLoading(true)

    const required = ['firstName', 'lastName', 'dob', 'phone', 'state', 'planType', 'premium', 'policyNumber', 'effectiveDate', 'draftDate', 'agentName'] as const
    const missing = required.filter(f => !form[f].trim())
    if (missing.length) {
      setError('Please fill in all required fields.')
      setLoading(false)
      return
    }

    if (form.phone.length !== 10) {
      setError('Phone number must be exactly 10 digits (e.g. 3055551234).')
      setLoading(false)
      return
    }

    if (form.zipCode && form.zipCode.length !== 5) {
      setError('ZIP code must be exactly 5 digits.')
      setLoading(false)
      return
    }

    if (!/^\d+(\.\d{0,2})?$/.test(form.premium)) {
      setError('Premium must be a valid dollar amount without the $ sign (e.g. 49.99).')
      setLoading(false)
      return
    }

    if (hasAddon && (!form.addonPolicyNumber.trim() || !form.addonPremium.trim())) {
      setError('Please fill in add-on policy number and premium.')
      setLoading(false)
      return
    }

    if (hasAddon && form.addonPremium && !/^\d+(\.\d{0,2})?$/.test(form.addonPremium)) {
      setError('Add-on premium must be a valid dollar amount without the $ sign (e.g. 29.99).')
      setLoading(false)
      return
    }

    try {
      const res = await fetch(`${API_URL}/api/deal-submission/submit/${agencySlug}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ ...form, hasAddon }),
      })
      const result = await res.json()
      if (!res.ok || !result.success) throw new Error(result.detail || result.error || 'Submission failed')
      setSuccess(result)
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Something went wrong.')
    } finally {
      setLoading(false)
    }
  }

  const resetForm = () => {
    setForm({
      firstName: '', lastName: '', dob: '', phone: '',
      address: '', city: '', state: '', zipCode: '',
      planType: '', premium: '', policyNumber: '',
      effectiveDate: '', draftDate: '', agentName: '',
      leadId: '',
      addonPlanType: '', addonPolicyNumber: '', addonPremium: '',
    })
    setHasAddon(false)
    setSuccess(null)
    setError('')
  }

  if (success) {
    return (
      <div className="min-h-screen bg-gray-50 flex items-center justify-center p-4">
        <div className="max-w-md w-full text-center">
          <div className="w-20 h-20 bg-green-50 border border-green-200 rounded-full flex items-center justify-center mx-auto mb-6">
            <CheckCircle className="w-10 h-10 text-green-500" />
          </div>
          <h2 className="text-3xl font-bold text-gray-900 mb-3">Deal Submitted!</h2>
          <p className="text-gray-500 mb-6">{success.message}</p>
          <div className="bg-white border border-gray-200 rounded-xl p-5 text-left text-sm text-gray-600 space-y-1.5 mb-6 shadow-sm">
            <p><strong className="text-gray-900">Customer:</strong> {form.firstName} {form.lastName}</p>
            <p><strong className="text-gray-900">Plan:</strong> {form.planType}</p>
            <p><strong className="text-gray-900">Premium:</strong> ${form.premium}</p>
            <p><strong className="text-gray-900">Policy #:</strong> {form.policyNumber}</p>
            <p><strong className="text-gray-900">Agent:</strong> {form.agentName}</p>
            {form.leadId && <p><strong className="text-gray-900">Lead ID:</strong> {form.leadId}</p>}
            {success.addonId && <p><strong className="text-gray-900">Add-on Policy #:</strong> {form.addonPolicyNumber}</p>}
          </div>
          <div className="flex gap-3 justify-center">
            <button onClick={resetForm} className="px-6 py-3 border border-gray-300 rounded-xl text-gray-600 hover:border-blue-500 hover:text-blue-600 transition text-sm font-semibold">
              Submit Another
            </button>
            <button onClick={() => navigate('/')} className="px-6 py-3 border border-gray-300 rounded-xl text-gray-600 hover:border-purple-500 hover:text-purple-600 transition text-sm font-semibold">
              Back to Leaderboard
            </button>
          </div>
        </div>
      </div>
    )
  }

  const inputClass = "w-full bg-white border border-gray-300 rounded-lg text-gray-900 text-sm py-2.5 px-3.5 outline-none transition focus:border-blue-500 focus:ring-2 focus:ring-blue-500/20 placeholder:text-gray-400"
  const selectClass = inputClass + " appearance-none cursor-pointer"
  const labelClass = "text-xs font-semibold tracking-wide uppercase text-gray-500"
  const sectionLabel = "text-xs font-bold tracking-widest uppercase text-gray-400 flex items-center gap-2.5 mt-7 mb-4"

  return (
    <div className="min-h-screen bg-gray-50">
      <div className="max-w-[720px] mx-auto px-6 py-12 pb-20">
        <button onClick={() => navigate('/')} className="inline-flex items-center gap-1.5 text-xs text-gray-500 font-semibold tracking-wider uppercase hover:text-blue-600 transition mb-8">
          <ArrowLeft className="w-3.5 h-3.5" /> Back to Leaderboard
        </button>

        <header className="mb-10">
          <div className="text-sm font-semibold tracking-widest uppercase text-blue-600 mb-2.5 flex items-center gap-2">
            <span className="block w-6 h-px bg-blue-500" />
            {agencyName} Portal
          </div>
          <h1 className="text-4xl font-extrabold leading-tight tracking-tight text-gray-900">
            Submit a <span className="text-blue-600">New Deal</span>
          </h1>
          <p className="mt-3 text-gray-500 text-base leading-relaxed">
            Fill out the enrollment details below. Contacts are created directly in GHL upon submission.
          </p>
        </header>

        <div className="bg-white border border-gray-200 rounded-2xl p-8 shadow-sm">
          <form onSubmit={handleSubmit}>
            <div className={sectionLabel}>Customer Information <span className="flex-1 h-px bg-gray-200" /></div>
            <div className="grid grid-cols-2 gap-3.5 max-sm:grid-cols-1">
              <div className="flex flex-col gap-1.5">
                <label className={labelClass}>First Name</label>
                <input type="text" name="firstName" value={form.firstName} onChange={handleChange} placeholder="Melissa" className={inputClass} />
              </div>
              <div className="flex flex-col gap-1.5">
                <label className={labelClass}>Last Name</label>
                <input type="text" name="lastName" value={form.lastName} onChange={handleChange} placeholder="Rodgers" className={inputClass} />
              </div>
              <div className="flex flex-col gap-1.5">
                <label className={labelClass}>Date of Birth</label>
                <input type="date" name="dob" value={form.dob} onChange={handleChange} className={inputClass} />
              </div>
              <div className="flex flex-col gap-1.5">
                <label className={labelClass}>Phone Number</label>
                <input type="tel" name="phone" value={form.phone} onChange={handleChange} placeholder="3055551234" maxLength={10} className={inputClass} />
                {form.phone.length > 0 && form.phone.length < 10 && <span className="text-xs text-amber-500">{10 - form.phone.length} digits remaining</span>}
              </div>
            </div>

            <div className={sectionLabel}>Address <span className="flex-1 h-px bg-gray-200" /></div>
            <div className="grid grid-cols-2 gap-3.5 max-sm:grid-cols-1">
              <div className="flex flex-col gap-1.5 col-span-2 max-sm:col-span-1">
                <label className={labelClass}>Street Address</label>
                <input type="text" name="address" value={form.address} onChange={handleChange} placeholder="123 Main St" className={inputClass} />
              </div>
              <div className="flex flex-col gap-1.5">
                <label className={labelClass}>City</label>
                <input type="text" name="city" value={form.city} onChange={handleChange} placeholder="Miami" className={inputClass} />
              </div>
              <div className="flex flex-col gap-1.5">
                <label className={labelClass}>State</label>
                <select name="state" value={form.state} onChange={handleChange} className={selectClass}>
                  <option value="">Select state</option>
                  {STATES.map(s => <option key={s} value={s}>{s}</option>)}
                </select>
              </div>
              <div className="flex flex-col gap-1.5">
                <label className={labelClass}>ZIP Code</label>
                <input type="text" name="zipCode" value={form.zipCode} onChange={handleChange} placeholder="33101" maxLength={5} className={inputClass} />
              </div>
            </div>

            <div className={sectionLabel}>Plan Details <span className="flex-1 h-px bg-gray-200" /></div>
            <div className="grid grid-cols-2 gap-3.5 max-sm:grid-cols-1">
              <div className="flex flex-col gap-1.5 col-span-2 max-sm:col-span-1">
                <label className={labelClass}>Plan Type</label>
                <select name="planType" value={form.planType} onChange={handleChange} className={selectClass}>
                  <option value="">Select plan type</option>
                  {PLAN_TYPES.map(p => <option key={p} value={p}>{p}</option>)}
                </select>
              </div>
              <div className="flex flex-col gap-1.5">
                <label className={labelClass}>Premium Amount</label>
                <input type="text" name="premium" value={form.premium} onChange={handleChange} placeholder="49.99" className={inputClass} />
                <span className="text-xs text-gray-400">Numbers only, no $ sign</span>
              </div>
              <div className="flex flex-col gap-1.5">
                <label className={labelClass}>Policy Number</label>
                <input type="text" name="policyNumber" value={form.policyNumber} onChange={handleChange} placeholder="20H6108873" className={inputClass} />
              </div>
              <div className="flex flex-col gap-1.5">
                <label className={labelClass}>Effective Date</label>
                <input type="date" name="effectiveDate" value={form.effectiveDate} onChange={handleChange} className={inputClass} />
              </div>
              <div className="flex flex-col gap-1.5">
                <label className={labelClass}>Premium Draft Date</label>
                <input type="date" name="draftDate" value={form.draftDate} onChange={handleChange} className={inputClass} />
              </div>
            </div>

            <div className={sectionLabel}>Agent <span className="flex-1 h-px bg-gray-200" /></div>
            <div className="grid grid-cols-2 gap-3.5 max-sm:grid-cols-1">
              <div className="flex flex-col gap-1.5">
                <label className={labelClass}>Agent Name</label>
                <select name="agentName" value={form.agentName} onChange={handleChange} className={selectClass}>
                  <option value="">{agents.length ? 'Select agent' : 'Loading agents...'}</option>
                  {agents.map(a => <option key={a} value={a}>{a}</option>)}
                </select>
              </div>
              <div className="flex flex-col gap-1.5">
                <label className={labelClass}>Lead ID</label>
                <input type="text" name="leadId" value={form.leadId} onChange={handleChange} placeholder="Lead ID" className={inputClass} />
              </div>
            </div>

            {/* Add-on toggle */}
            <div
              onClick={() => setHasAddon(!hasAddon)}
              className={`mt-6 p-4 px-5 rounded-lg flex items-center gap-3.5 cursor-pointer transition border ${hasAddon ? 'bg-blue-50 border-blue-300' : 'bg-gray-50 border-gray-200 hover:bg-blue-50/50'}`}
            >
              <div className={`w-10 h-[22px] rounded-full relative transition ${hasAddon ? 'bg-blue-500' : 'bg-gray-300'}`}>
                <div className={`absolute top-[3px] left-[3px] w-4 h-4 rounded-full bg-white transition-transform ${hasAddon ? 'translate-x-[18px]' : ''}`} />
              </div>
              <div>
                <div className="text-sm font-semibold text-gray-900">Add Spouse / Dental</div>
                <div className="text-xs text-gray-500 mt-0.5">Submit a second contact with a separate policy & premium</div>
              </div>
            </div>

            {/* Add-on fields */}
            <div className={`mt-4 rounded-lg bg-blue-50 border border-blue-200 overflow-hidden transition-all duration-300 ${hasAddon ? 'max-h-[400px] opacity-100 p-5' : 'max-h-0 opacity-0 p-0 border-transparent'}`}>
              <div className={sectionLabel + ' !mt-0'}>Second Policy Details <span className="flex-1 h-px bg-gray-200" /></div>
              <div className="grid grid-cols-2 gap-3.5 max-sm:grid-cols-1">
                <div className="flex flex-col gap-1.5 col-span-2 max-sm:col-span-1">
                  <label className={labelClass}>Plan Type (Add-On)</label>
                  <select name="addonPlanType" value={form.addonPlanType} onChange={handleChange} className={selectClass}>
                    <option value="">Same as primary</option>
                    {PLAN_TYPES.map(p => <option key={p} value={p}>{p}</option>)}
                  </select>
                </div>
                <div className="flex flex-col gap-1.5">
                  <label className={labelClass}>Policy Number</label>
                  <input type="text" name="addonPolicyNumber" value={form.addonPolicyNumber} onChange={handleChange} placeholder="Second policy #" className={inputClass} />
                </div>
                <div className="flex flex-col gap-1.5">
                  <label className={labelClass}>Premium Amount</label>
                  <input type="text" name="addonPremium" value={form.addonPremium} onChange={handleChange} placeholder="29.99" className={inputClass} />
                  <span className="text-xs text-gray-400">Numbers only, no $ sign</span>
                </div>
              </div>
            </div>

            {error && (
              <div className="mt-4 p-3.5 rounded-lg bg-red-50 border border-red-200 text-red-600 text-sm flex items-center gap-2">
                <AlertTriangle className="w-4 h-4 flex-shrink-0" /> {error}
              </div>
            )}

            <button
              type="submit"
              disabled={loading}
              className="mt-7 w-full py-3.5 px-6 bg-blue-600 hover:bg-blue-700 rounded-lg text-white text-sm font-bold tracking-wide uppercase cursor-pointer transition disabled:opacity-50 disabled:cursor-not-allowed"
            >
              {loading ? <Loader2 className="w-4 h-4 animate-spin mx-auto" /> : 'Submit Enrollment'}
            </button>
          </form>
        </div>
      </div>
    </div>
  )
}
