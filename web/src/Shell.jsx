import { useEffect, useState } from 'react'

import App from './App.jsx'
import Playground from './Playground.jsx'

/**
 * Two tabs, conditional rendering, no router.
 *
 * `CLAUDE.md` rules out component kits and CSS-in-JS on the grounds that a dependency is forever;
 * pulling in react-router for two tabs is the same instinct wearing a different hat. If this ever
 * grows real routes — deep links, back-button semantics — that is the trigger to revisit.
 *
 * `config` is fetched once here and passed down rather than fetched per tab: it is the same data,
 * it does not change while the page is open, and two fetches would be two chances to disagree.
 */
export default function Shell() {
  const [tab, setTab] = useState('chat')
  const [config, setConfig] = useState(null)

  useEffect(() => {
    fetch('/api/config')
      .then((r) => (r.ok ? r.json() : null))
      .then(setConfig)
      .catch(() => setConfig(null)) // the chat tab works without it; the strip just stays hidden
  }, [])

  return (
    <div className="shell">
      <nav className="tabs" aria-label="Views">
        <button
          className={tab === 'chat' ? 'tab tab--on' : 'tab'}
          onClick={() => setTab('chat')}
          aria-current={tab === 'chat' ? 'page' : undefined}
        >
          Chat
        </button>
        <button
          className={tab === 'playground' ? 'tab tab--on' : 'tab'}
          onClick={() => setTab('playground')}
          aria-current={tab === 'playground' ? 'page' : undefined}
        >
          Playground
        </button>
      </nav>

      {/* Both stay mounted: switching tabs must not discard a conversation or a result. Hiding
          with CSS rather than unmounting is what makes the chat tab's history survive a click. */}
      <div className={tab === 'chat' ? 'view' : 'view view--hidden'}>
        <App />
      </div>
      <div className={tab === 'playground' ? 'view' : 'view view--hidden'}>
        <Playground config={config} />
      </div>
    </div>
  )
}
