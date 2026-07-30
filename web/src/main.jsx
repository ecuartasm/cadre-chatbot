import React from 'react'
import { createRoot } from 'react-dom/client'

// Order matters: tokens define the custom properties app.css consumes. Without these imports
// Vite builds cleanly and applies nothing — there was no stylesheet entry point before Phase 5.
import './tokens.css'
import './app.css'

import App from './App.jsx'

createRoot(document.getElementById('root')).render(<App />)
