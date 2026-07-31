# Plan — `/chat-widget`: the bot as a floating widget on a Cadre-styled page

**Standalone. This is deliberately NOT in `plan.md` or `CLAUDE.md`** — it is an additional showcase
feature, not part of the graded brief, and folding it into either document would misrepresent the
scope that was actually specified. Nothing here changes the product's contract. If it is ever
promoted from "demo" to "delivered", that is the moment to move it.

**Goal.** A second page at `http://127.0.0.1:8000/chat-widget` showing a Cadre-styled marketing page
with the support bot as a floating launcher in the corner, opening into a chat panel — i.e. how this
would actually be embedded on cadreai.com, rather than as a full-page app.

**Why it is worth building.** The chat page proves the bot works. This proves it *fits*: the same
API, the same boundary, the same refusals, in the form a client would actually deploy. It is the
difference between a demo and a product illustration.

---

## The decisive finding: zero backend changes

Measured, not assumed. `app/main.py` mounts the bundle as
`StaticFiles(directory=WEB_DIST, html=True)` at `/`, and `html=True` already resolves a directory to
its `index.html`. With a Vite multi-page build emitting `dist/chat-widget/index.html`:

```
/                200   (the existing app)
/chat-widget     200   (serves chat-widget/index.html)
/chat-widget/    200
```

Verified against a real `TestClient` before writing this plan. **No FastAPI route, no router, no
change to route ordering.** The whole feature lives in `web/`.

Everything else comes free from the existing seams: `/api/chat` is unchanged, so the 8-turn history
bound, the rate limiter, the daily spend cap, the refusal marker stripping, the inbound-marker
sanitising, and per-turn cost logging all apply to the widget identically. That is the seam doing
its job — **if this feature required touching `app/`, the seam would be wrong.**

---

## Decision: a mockup, not a clone

`analysis/Cadre AI _ ….html` exists, and using it directly was evaluated and rejected. Measured:

| | |
|---|---|
| Absolute external URLs | **94** |
| → `cdn.prod.website-files.com` (Webflow) | **81** — all CSS, fonts, images |
| Hotlinked `<img>` | **74** |
| External stylesheets | **1** — the entire site CSS |
| External scripts | **12** |
| Root-relative links (`/about`, `/contact`) | **119** — would resolve against our own origin |
| Third-party trackers | Wistia, `api.consentpro.com` |

Three reasons it is the wrong input:

1. **It does not render offline.** Every pixel comes from Webflow's CDN. A demo that dies on bad
   conference wifi is the exact failure the "never search the web at runtime" rule was written to
   avoid — it would be strange to hold the bot to that standard and not the page around it.
2. **It is gitignored** (`.gitignore:42`, `analysis/*.html`), so it cannot ship. Un-ignoring a 129 KB
   scrape of someone's marketing site to make a demo work is a bad trade.
3. **It runs third-party scripts** — a consent-management tracker and Wistia would load on our page.

**Instead: build the page from tokens we already own.** `web/src/tokens.css` has 39 custom
properties including `--cadre-blue: #08749b`, `--cadre-red: #db4545`, `--cadre-sand: #faf9f6`,
`--font-display: 'Inter Tight'`, and the fonts are already self-hosted.
`analysis/brand-tokens-extracted.txt` records the *declared* values pulled from the real Webflow
stylesheet, so the palette is accurate rather than eyeballed.

Result: self-contained, offline, no trackers, no hotlinking, and it reads as an obvious
illustration rather than a copy.

### ⚠️ It must not be mistakable for the real site

A page built to look like Cadre AI's marketing site, served from a URL that is not theirs, stops
being a mockup the moment someone lands on it out of context. Non-negotiable for this feature:

- A visible **"Demo — not the real Cadre AI website"** banner or ribbon, present at every viewport.
- **No login form, no credential fields, no email capture.** A "Log in" *link* pointing at
  `/contact` is fine; a form with password inputs on a page imitating a real company is
  phishing-shaped regardless of intent.
- Placeholder copy that is clearly illustrative — headline and section text drawn from the corpus
  (which is public), not fabricated claims.
- Every outbound link goes to a **real** cadreai.com page, using the same allowlist the chat renderer
  already enforces (`web/src/cadre-urls.js`).

Railway currently stays offline except when demoing, which is the practical containment. If that
ever changes, this page is the first thing to re-examine.

---

## Steps

### 1. Extract the chat logic into `useChat()` — the real work

`web/src/App.jsx` is 165 lines with the entire conversation engine inline: `send()` spans roughly
lines 29–110 and owns the message array, the `fetch`, the SSE reader, frame buffering across reads,
delta accumulation, error frames, and first-token timing.

The widget needs all of it. **Copying it would create a second SSE parser**, and the two would drift
— the marker handling and `done`-frame shape are exactly the things that have moved twice already.

Extract to `web/src/useChat.js` returning `{ messages, input, setInput, send, streaming, firstTokenMs }`.
Mechanical, behaviour-preserving, no logic change.

**Exit:** `App.jsx` renders the same as before and its tests pass unchanged; the hook has no JSX and
no knowledge of which surface is using it.

⚠️ **Three tests call `code(APP)` directly** (`tests/test_ui.py:131, 221, 228`) and assert on strings
that are about to move into the hook. `CLAUDE.md` already warns that checks pinned to `App.jsx`
"silently stop covering the UI if a component moves" — a guard that narrows is worse than one that
fails, because it still reports green. **Widen these to the component glob as part of this step, not
after.**

### 2. Vite multi-page build

`web/vite.config.js` is currently single-entry (implicit `web/index.html`). Add:

```js
build: { rollupOptions: { input: { main: 'index.html', 'chat-widget': 'chat-widget/index.html' } } }
```

with `web/chat-widget/index.html` as the second entry and `web/src/widget-main.jsx` as its root.

**Exit:** `npm run build` emits `dist/index.html` *and* `dist/chat-widget/index.html`; both load
their own hashed assets; the existing page is byte-identical in behaviour.

⚠️ Vite hashes asset filenames, and a browser holding a cached `index.html` will request assets that
no longer exist — this bit the project once already. Hard-reload when checking.

### 3. The mockup page

A single scrolling page in Cadre's visual language, entirely from `tokens.css`:

- Sticky nav — wordmark, a few section links, a "Book a call" button → `/contact`
- Hero — headline, subhead, primary CTA
- Three or four sections: services, industries (the nine are corpus-backed), a metric strip, footer
- The demo banner from the section above

**Exit:** renders offline with the network disabled; no request leaves the origin; passes the
existing "no literal colours outside `tokens.css`" and "all text black" checks.

### 4. The floating widget

`web/src/Widget.jsx` — launcher button, panel, and the transcript reusing `useChat()` and
`renderInline()` so links, bold and refusals behave exactly as in the full page.

Requirements that are easy to skip and obvious when missing:

- **Focus moves into the panel on open and returns to the launcher on close.** Escape closes.
- `aria-expanded` on the launcher, `role="dialog"` + `aria-label` on the panel, `aria-live` on the
  transcript — the full-page chat already sets this precedent.
- **Panel height in `dvh`/`svh`, input `≥16px`** — `vh` breaks under the iOS keyboard and a smaller
  input triggers iOS auto-zoom. Both are documented rules, both are invisible on a desktop browser.
- On narrow viewports the panel goes full-screen rather than floating.
- Respect `prefers-reduced-motion` for the open/close transition.
- The panel must not trap scroll on the page behind it when closed.

**Exit:** keyboard-only operation works end to end; the widget opens, asks, streams, refuses, and
routes to `/contact` as a real link.

### 5. Verification

- `pytest && ruff check .` — including the widened UI tests
- Build, hard-reload, and walk the six scenarios through the **widget** specifically. It shares the
  API, so this is checking the surface, not the bot.
- Confirm a refusal still tags: ask for pricing in the widget and check `status="refused"` on the
  `done` frame. The marker path is shared, but "shared" is an assumption until it is observed.
- Confirm **no request leaves the origin** with the network panel open — this is the mockup's whole
  claim.
- Screenshot the widget open and closed for the report. I cannot see rendered pages; visual sign-off
  is yours.

---

## Out of scope, deliberately

- **An embeddable script tag for third parties** (`<script src="…/widget.js">`). That is a real
  product with real problems — CORS, CSP, style isolation, versioning, an origin allowlist. This
  demo is same-origin, which is why it is a day and not a fortnight.
- **A login page or any credential field.** See the mockup section; `plan.md` already has
  "Auth / real portal access — never, for this brief".
- **Cloning the real HTML.** Evaluated and rejected above.
- **Routing.** Two static pages, no router — the same reasoning `Shell.jsx` gives for two tabs.
- **Widget state persisting across page loads.** Cross-session persistence is already out of scope
  for the product; the widget should not quietly acquire it.

---

## Risks

| Risk | Mitigation |
|---|---|
| The hook extraction changes chat behaviour subtly | Mechanical refactor first, committed separately, with the existing tests green *before* the widget exists |
| Tests pinned to `App.jsx` pass while covering nothing | Widen them in step 1, not later — this failure mode has already occurred here |
| The mockup reads as the real site | Demo banner, no credential fields, allowlisted links only |
| Mobile keyboard breaks the panel | `dvh`/`svh` and `≥16px` input, checked on a real phone viewport |
| Two SSE parsers drift | There is only one — that is the point of step 1 |

---

## Estimate

| Step | |
|---|---|
| 1. `useChat()` extraction + widen tests | 45–60 min |
| 2. Vite multi-page | 15 min |
| 3. Mockup page | 45–60 min |
| 4. Widget | 60–75 min |
| 5. Verification + report | 30 min |
| **Total** | **~3.5 hours** |

Backend: **zero**.

## Exit criteria

1. `http://127.0.0.1:8000/chat-widget` serves the mockup with the widget closed by default.
2. Clicking the launcher opens a panel that streams a real answer from `/api/chat`.
3. A pricing question refuses in the widget and reports `status="refused"` on the `done` frame.
4. The page renders fully with the network disabled after first load; no cross-origin requests.
5. Keyboard-only: open, type, send, read, close — focus returns to the launcher.
6. `pytest && ruff check .` green, with the previously `App.jsx`-pinned tests now covering all
   components.
7. The existing `/` app is unchanged in behaviour.
8. A short section in `reports/testing_adjusting.md` — not a new phase report, since this is not a
   phase.
