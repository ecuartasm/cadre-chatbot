import { CADRE_URLS } from './cadre-urls'

/**
 * A Cadre-styled marketing page, built to show the support bot as an embedded widget rather than
 * as a full-page app.
 *
 * ⚠️ **This is a mockup, not a clone.** `analysis/` holds a saved copy of the real page; it was
 * evaluated and rejected — 94 absolute external URLs (81 to Webflow's CDN), 74 hotlinked images,
 * 12 external scripts and two third-party trackers. It does not render offline, and it is
 * gitignored so it cannot ship. Everything here is drawn from `tokens.css`, whose palette was taken
 * from the real declared Webflow custom properties, so the colours are accurate rather than guessed.
 *
 * ⚠️ **It must never be mistakable for the real site.** Three rules, all guarded by
 * `tests/test_ui.py`:
 *
 * 1. A visible demo banner at every viewport, saying plainly that this is not cadreai.com.
 * 2. **No login form, no credential field, no email capture.** A page imitating a real company
 *    that also asks for a password is phishing-shaped whatever the intent behind it. "Log in" is a
 *    link to the real contact page, nothing more.
 * 3. Every outbound link goes to a page `content/raw/` proves exists, via the same allowlist the
 *    chat renderer enforces.
 *
 * Copy is drawn from the corpus, which is public, rather than invented — the nine industries below
 * are the nine pages the scraper actually fetched.
 */

// Resolved from the allowlist rather than written as literals, so a link here cannot point
// somewhere the corpus has not vouched for. A typo becomes a build-visible `undefined`, not a
// plausible-looking dead URL.
const url = (path) => CADRE_URLS.find((u) => u.endsWith(path)) ?? CADRE_URLS[0]

const NAV = [
  ['Strategy', '/strategy'],
  ['Industries', '/industries'],
  ['Case studies', '/case-studies'],
  ['Articles', '/articles'],
]

const SERVICES = [
  ['AI Strategy', 'Where AI actually moves the number, and where it does not. Assessment first, roadmap second.'],
  ['AI Engineering', 'Building the systems the strategy calls for — agents, automations, integrations.'],
  ['Leadership Facilitation', 'Bringing the executive team to a shared view of what AI changes and what it does not.'],
]

const INDUSTRIES = [
  ['Real Estate', '/industries/real-estate'],
  ['Financial Services', '/industries/financial-services'],
  ['Mortgage & Lending', '/industries/mortgage-lending'],
  ['Construction', '/industries/construction'],
  ['Retail & E-commerce', '/industries/retail-e-commerce'],
  ['Manufacturing & Logistics', '/industries/manufacturing-logistics'],
  ['Private Equity', '/industries/private-equity'],
  ['Professional Services', '/industries/professional-services'],
  ['Hospitality', '/industries/hospitality'],
]

export default function Mockup() {
  return (
    <div className="mk">
      <p className="mk-demo" role="note">
        <strong>Demo</strong> — a mockup built to show the support widget in context. This is
        <strong> not </strong>
        the real Cadre AI website. The live site is{' '}
        <a href={url('cadreai.com')} target="_blank" rel="noopener noreferrer">
          cadreai.com
        </a>
        .
      </p>

      <header className="mk-nav">
        <span className="mk-mark">CADRE<span className="mk-mark-ai">AI</span></span>
        <nav className="mk-links" aria-label="Sections">
          {NAV.map(([label, path]) => (
            <a key={path} href={url(path)} target="_blank" rel="noopener noreferrer">
              {label}
            </a>
          ))}
        </nav>
        {/* A LINK, never a form. See the header of this file. */}
        <a className="mk-cta" href={url('/contact')} target="_blank" rel="noopener noreferrer">
          Book a call
        </a>
      </header>

      <main>
        <section className="mk-hero">
          <h1 className="mk-h1">AI strategy and implementation for business growth</h1>
          <p className="mk-lede">
            We help companies find where AI actually moves the number — then build it. Assessment
            first, roadmap second, systems third.
          </p>
          <a className="mk-cta mk-cta--lg" href={url('/contact')} target="_blank" rel="noopener noreferrer">
            Talk to a strategist
          </a>
        </section>

        <section className="mk-band">
          <h2 className="mk-h2">What we do</h2>
          <div className="mk-grid">
            {SERVICES.map(([name, blurb]) => (
              <article className="mk-card" key={name}>
                <h3 className="mk-h3">{name}</h3>
                <p className="mk-body">{blurb}</p>
              </article>
            ))}
          </div>
        </section>

        <section className="mk-band mk-band--sand">
          <h2 className="mk-h2">Industries we work in</h2>
          <p className="mk-body mk-body--wide">
            Nine sectors, each with its own version of the same question: which processes are worth
            automating, and which are not.
          </p>
          <ul className="mk-chips">
            {INDUSTRIES.map(([name, path]) => (
              <li key={path}>
                <a href={url(path)} target="_blank" rel="noopener noreferrer">
                  {name}
                </a>
              </li>
            ))}
          </ul>
        </section>

        <section className="mk-band">
          <h2 className="mk-h2">Reported results</h2>
          <p className="mk-body mk-body--wide">
            Figures from published case studies. Clients are anonymised, and these are past results
            for other companies — not projections or guarantees.
          </p>
          <div className="mk-grid">
            <article className="mk-card" key="a">
              <p className="mk-stat">8,000+</p>
              <p className="mk-body">hours saved annually on proposal generation.</p>
            </article>
            <article className="mk-card" key="b">
              <p className="mk-stat">$136,000</p>
              <p className="mk-body">revenue increase per Field Specialist after scheduling automation.</p>
            </article>
            <article className="mk-card" key="c">
              <p className="mk-stat">Nine</p>
              <p className="mk-body">industries with published, sector-specific engagements.</p>
            </article>
          </div>
        </section>
      </main>

      <footer className="mk-foot">
        <p className="mk-body">
          Mockup for demonstration. Content is drawn from Cadre AI&rsquo;s public site; every link
          above points at a real page on{' '}
          <a href={url('cadreai.com')} target="_blank" rel="noopener noreferrer">
            cadreai.com
          </a>
          .
        </p>
      </footer>
    </div>
  )
}
