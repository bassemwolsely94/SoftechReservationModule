import React from 'react'
import ReactDOM from 'react-dom/client'
import App from './App.jsx'
import { ToastProvider } from './components/ui.jsx'
import './index.css'

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
