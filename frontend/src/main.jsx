import React from 'react'
import ReactDOM from 'react-dom/client'
import App from './App.jsx'
import ErrorBoundary from './components/ErrorBoundary'
import { ToastProvider } from './components/ui.jsx'
import './index.css'
import { applyTheme, loadCachedTheme, cacheTheme, applyMode, watchSystemMode } from './theme/theme'
import { configApi } from './api/client'

// Apply the personal light/dark mode + brand theme before first paint (cached →
// no flash). Mode is per-device (localStorage); the brand theme then syncs with
// the server-side global theme. Public endpoint, so this works pre-login too.
applyMode()          // reads localStorage['app_theme_mode'] (defaults to 'system')
watchSystemMode()    // keep 'system' live against the OS preference
applyTheme(loadCachedTheme() || undefined)
configApi.getTheme()
  .then(({ data }) => { applyTheme(data); cacheTheme(data) })
  .catch(() => {})

// Create toast portal root
const toastRoot = document.createElement('div')
toastRoot.id = 'toast-root'
document.body.appendChild(toastRoot)

ReactDOM.createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    {/* last safety net — never a blank screen (a page-level boundary sits in each layout) */}
    <ErrorBoundary scope="app">
      <ToastProvider>
        <App />
      </ToastProvider>
    </ErrorBoundary>
  </React.StrictMode>,
)
