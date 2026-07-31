import { createRoot } from 'react-dom/client'

// Order matters: tokens define the custom properties the other two consume. Without these imports
// Vite builds cleanly and applies nothing — the failure `test_the_stylesheets_are_actually_imported`
// exists to catch, and the reason that test is parametrised over every entry point rather than
// hardcoded to main.jsx.
//
// app.css comes along because the widget reuses `.message`, `.message--error` and `.caret` from the
// full-page chat rather than restating them.
import './tokens.css'
import './app.css'
import './widget.css'

import Mockup from './Mockup.jsx'
import Widget from './Widget.jsx'

/**
 * Entry point for `/chat-widget` — the Cadre-styled mockup with the support bot as a floating
 * widget, showing how it would actually be embedded rather than as a full-page app.
 *
 * Served with no FastAPI route: `StaticFiles(html=True)` resolves `dist/chat-widget/` to its
 * index.html. See vite.config.js.
 */
createRoot(document.getElementById('root')).render(
  <>
    <Mockup />
    <Widget />
  </>
)
