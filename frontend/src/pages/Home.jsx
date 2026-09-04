import { Link } from 'react-router-dom';
import { Scale, Shield, Doc, Leaf, Check, Search, Flask, Globe } from '../components/Icons.jsx';
import { Badge, Disclaimer } from '../components/Bits.jsx';

/* The landing page carries the "understood by everyone" load: a vaidya or a
   small manufacturer arrives here not knowing what ABS is, or that section
   3(p) exists. Plain language first, terms of art introduced afterward. */

const PILLARS = [
  {
    icon: <Scale size={22} />,
    title: 'Answers you can check',
    body: 'Every answer names the Act and the section it came from, with the exact text beside it. When the law doesn’t clearly cover your question, it says so instead of guessing.',
  },
  {
    icon: <Shield size={22} />,
    title: 'Compliance you didn’t know to ask about',
    body: 'Using an Indian plant in your formulation can require National Biodiversity Authority approval before a patent is granted. That check runs on every question — you don’t have to know it exists.',
  },
  {
    icon: <Doc size={22} />,
    title: 'From question to filing',
    body: 'Turn a case into structured intake, prior-art and biodiversity pre-checks, draft form content and tracked deadlines — ready to hand to a registered patent agent.',
  },
];

const STEPS = [
  { n: '1', t: 'Ask in your language', d: 'Type your question in Hindi, Tamil, Bengali or any of nine languages. It’s translated for search and the answer comes back in the language you asked in.' },
  { n: '2', t: 'The law is retrieved', d: 'Your question is matched against ingested statutes, rules and treaties — filtered to your jurisdiction and formulation type before anything is searched.' },
  { n: '3', t: 'Obligations are screened', d: 'A regulatory knowledge graph works out which duties apply to your specific facts, which exemptions remove them, and in what order they fall due.' },
  { n: '4', t: 'You get a cited answer', d: 'With the sections quoted, a confidence reading, and an honest list of what the system still needs to know before it can be sure.' },
];

export default function Home() {
  return (
    <>
      <section className="shell hero">
        <div className="hero-grid">
          <div className="rise">
            <span className="eyebrow">Ayurveda · Intellectual property · Regulatory compliance</span>
            <h1 style={{ marginTop: 14 }}>
              Know where your formulation stands — <em>before</em> you file.
            </h1>
            <p className="hero-lede">
              Ask a plain question about patenting an Ayurvedic formulation and get an answer grounded in
              the actual sections of Indian law — along with the biodiversity and disclosure obligations
              most applicants only discover after a refusal.
            </p>
            <div className="hero-cta">
              <Link to="/ask" className="btn btn-primary">
                <Search size={18} /> Ask a question
              </Link>
              <Link to="/cases" className="btn btn-ghost">See a worked case</Link>
            </div>
            <div className="row-wrap" style={{ marginTop: 24, gap: 14 }}>
              {['9 Indian languages', 'Cited to section level', 'Abstains when unsure'].map(t => (
                <span key={t} className="row faint" style={{ fontSize: 13.6, gap: 7 }}>
                  <Check size={15} style={{ color: 'var(--ok)' }} /> {t}
                </span>
              ))}
            </div>
          </div>

          {/* A miniature of a real answer — shows the product in one glance. */}
          <div className="hero-panel rise" style={{ animationDelay: '90ms' }}>
            <p className="hero-panel-q">
              “क्या पारंपरिक आयुर्वेदिक फ़ॉर्मूलेशन का पेटेंट कराया जा सकता है?”
            </p>
            <div className="row" style={{ gap: 8, marginBottom: 12, flexWrap: 'wrap' }}>
              <Badge tone="ok">Answered · 83%</Badge>
              <Badge tone="stop">2 blocking duties</Badge>
            </div>
            <p style={{ fontSize: 14.6, lineHeight: 1.6, color: 'var(--text-muted)' }}>
              Unlikely as such — section 3(p) excludes an invention that is, in effect, traditional
              knowledge. A novel process over that base may still qualify…
            </p>
            <div style={{ marginTop: 14, paddingTop: 13, borderTop: '1px solid var(--border)' }}>
              {[['1', 'The Patents Act, 1970', 'Section 3(p)'], ['2', 'Biological Diversity Act, 2002', 'Section 6']].map(([n, act, sec]) => (
                <div key={n} className="row" style={{ gap: 10, marginTop: 8 }}>
                  <span className="cite-n" style={{ width: 22, height: 22, fontSize: 11 }}>{n}</span>
                  <span style={{ fontSize: 13.4, minWidth: 0 }}>
                    <strong style={{ fontWeight: 600 }}>{act}</strong>
                    <span className="faint"> · {sec}</span>
                  </span>
                </div>
              ))}
            </div>
          </div>
        </div>
      </section>

      <section className="shell">
        <div className="stat-strip">
          {[
            ['9', 'languages supported'],
            ['12', 'instruments in the corpus'],
            ['14', 'obligations modelled'],
            ['3(p)', 'the section most applicants miss'],
          ].map(([n, l]) => (
            <div className="stat" key={l}>
              <div className="stat-n">{n}</div>
              <div className="stat-l">{l}</div>
            </div>
          ))}
        </div>
      </section>

      <section className="shell section">
        <div className="section-head">
          <h2>Built for the person who doesn’t have a patent lawyer yet</h2>
          <p>
            A practitioner, a small manufacturer, a research collective. The system assumes you know
            your formulation — not the statute book.
          </p>
        </div>
        <div className="features">
          {PILLARS.map((p, i) => (
            <div className="feature rise" key={p.title} style={{ animationDelay: `${i * 70}ms` }}>
              <div className="feature-ico">{p.icon}</div>
              <h3>{p.title}</h3>
              <p>{p.body}</p>
            </div>
          ))}
        </div>
      </section>

      <section className="shell section">
        <div className="section-head">
          <h2>How an answer is put together</h2>
          <p>Four steps, and you can inspect the evidence at every one of them.</p>
        </div>
        <div style={{ display: 'grid', gap: 14 }}>
          {STEPS.map((s, i) => (
            <div className="card rise" key={s.n} style={{ padding: '22px 24px', animationDelay: `${i * 60}ms` }}>
              <div style={{ display: 'flex', gap: 20, alignItems: 'flex-start' }}>
                <span style={{
                  flexShrink: 0, width: 38, height: 38, borderRadius: 12,
                  display: 'grid', placeItems: 'center',
                  background: 'var(--bg-sunken)', border: '1px solid var(--border)',
                  fontFamily: 'var(--font-display)', fontSize: 17, fontWeight: 600,
                  color: 'var(--brand-text)',
                }}>{s.n}</span>
                <div>
                  <h3 style={{ fontSize: 18, marginBottom: 6 }}>{s.t}</h3>
                  <p className="muted" style={{ fontSize: 14.8, lineHeight: 1.62, maxWidth: '68ch' }}>{s.d}</p>
                </div>
              </div>
            </div>
          ))}
        </div>
      </section>

      <section className="shell section">
        <div className="card" style={{ padding: 32, display: 'grid', gap: 20 }}>
          <div className="row" style={{ gap: 12 }}>
            <span className="feature-ico" style={{ margin: 0, width: 38, height: 38 }}><Flask size={19} /></span>
            <h2 style={{ fontSize: 24 }}>What it will not do</h2>
          </div>
          <div className="features" style={{ gap: 16 }}>
            {[
              ['It won’t guess.', 'When retrieval is too weak, the answer is an explicit abstention — not a confident-sounding paragraph built on nothing.'],
              ['It won’t hide its sources.', 'Every citation opens to the section text it came from, so you can judge the answer rather than trust it.'],
              ['It won’t replace your agent.', 'Filing decisions, form mechanics and anything adversarial belong with a registered patent agent. This gets you to that conversation prepared.'],
            ].map(([t, d]) => (
              <div key={t}>
                <h3 style={{ fontSize: 16.5, marginBottom: 7 }}>{t}</h3>
                <p className="muted" style={{ fontSize: 14.4, lineHeight: 1.6 }}>{d}</p>
              </div>
            ))}
          </div>
          <Disclaimer>
            Automated regulatory screening is informational only. Every obligation must be confirmed
            against the bare text of the cited provision, and with a registered patent agent or
            counsel, before it is acted on.
          </Disclaimer>
        </div>
      </section>

      <section className="shell section">
        <div style={{
          borderRadius: 'var(--r-xl)', padding: '44px 36px', textAlign: 'center',
          background: 'linear-gradient(150deg, var(--green-700), var(--green-900))',
          boxShadow: 'var(--shadow-lg)', color: '#fff',
        }}>
          <Leaf size={34} style={{ color: 'var(--turmeric-400)', marginBottom: 14 }} />
          <h2 style={{ color: '#fff', fontSize: 'clamp(25px, 3.6vw, 34px)', marginBottom: 12 }}>
            Start with the question you actually have.
          </h2>
          <p style={{ color: 'rgba(255,255,255,.82)', maxWidth: '52ch', margin: '0 auto 26px', fontSize: 16.5, lineHeight: 1.6 }}>
            No account, no jargon. Ask in your own language and see exactly which law the answer rests on.
          </p>
          <Link to="/ask" className="btn btn-accent">
            <Globe size={18} /> Ask in your language
          </Link>
        </div>
      </section>
    </>
  );
}
