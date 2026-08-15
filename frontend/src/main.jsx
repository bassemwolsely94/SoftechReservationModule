import React from 'react'
import ReactDOM from 'react-dom/client'
import App from './App.jsx'
import { ToastProvider } from './components/ui.jsx'
import './index.css'
import { applyTheme, loadCachedTheme, cacheTheme } from './theme/theme'
import { configApi } from './api/client'

// Apply the brand theme before first paint (cached → no flash), then sync with
// the server-side global theme. Public endpoint, so this works pre-login too.
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
    <ToastProvider>
      <App />
    </ToastProvider>
  </React.StrictMode>,
)
