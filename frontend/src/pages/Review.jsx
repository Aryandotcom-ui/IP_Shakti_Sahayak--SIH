import { useState, useEffect } from 'react';
import { api } from '../lib/api.js';
import { useDemo } from '../App.jsx';
import { Refresh, Alert, Check, Clock, Shield } from '../components/Icons.jsx';
import { Badge, Empty, Explain, Disclaimer } from '../components/Bits.jsx';

/* The review gate. Framed for the corpus maintainer: what changed upstream,
   what the classifier decided, and what still needs a human. */

const TIER = {
  auto_publish:       { tone: 'ok',   label: 'Auto-published', blurb: 'Small change on a trusted official source — ingested without waiting for a person.' },
  publish_then_audit: { tone: 'warn', label: 'Published, needs audit', blurb: 'Big enough to matter. Live already so the corpus doesn’t lag, but flagged for sign-off.' },
  mandatory_review:   { tone: 'stop', label: 'Held for review', blurb: 'Nothing ingested. A person decides before this reaches the corpus.' },
};

export default function Review() {
  const [tab, setTab] = useState('pending');
  const [rows, setRows] = useState(null);
  const { setDemo } = useDemo();

  useEffect(() => {
    setRows(null);
    const fn = tab === 'pending' ? api.reviewPending
      : tab === 'audit' ? api.reviewNeedsAudit : api.reviewHistory;
    fn().then(r => { if (r.demo) setDemo(true); setRows(r.data); });
  }, [tab, setDemo]);

  return (
    <div className="shell" style={{ maxWidth: 980 }}>
      <div style={{ marginBottom: 24 }}>
        <span className="eyebrow">Corpus review</span>
        <h1 style={{ fontSize: 'clamp(30px, 4vw, 40px)', margin: '10px 0 10px' }}>
          What changed in the law
        </h1>
        <p className="muted" style={{ fontSize: 16, maxWidth: '68ch' }}>
          Sources are watched for changes. How each change is handled depends on how much is at stake —
          a small edit to a trusted portal publishes itself; anything touching a critical Act waits for
          a person.
          <Explain>
            A byte-level diff can tell that something changed, never whether a comma moved or section 6
            was rewritten. So severity is decided by the source’s declared risk, not the size of the diff.
          </Explain>
        </p>
      </div>

      <div className="features" style={{ gap: 14, marginBottom: 28 }}>
        {Object.entries(TIER).map(([k, t]) => (
          <div className="feature" key={k} style={{ padding: 20 }}>
            <Badge tone={t.tone}>{t.label}</Badge>
            <p className="muted" style={{ fontSize: 13.8, lineHeight: 1.58, marginTop: 11 }}>{t.blurb}</p>
          </div>
        ))}
      </div>

      <div className="tabs" role="tablist">
        {[['pending', 'Awaiting review'], ['audit', 'Needs sign-off'], ['history', 'History']].map(([k, l]) => (
          <button key={k} role="tab" className="tab" aria-selected={tab === k} onClick={() => setTab(k)}>{l}</button>
        ))}
      </div>

      {!rows && <div className="skeleton" style={{ height: 160, borderRadius: 14 }} />}

      {rows?.length === 0 && (
        <Empty icon={<Check size={26} />} title="Nothing waiting">
          {tab === 'pending'
            ? 'No upstream change is currently held for a decision.'
            : tab === 'audit'
              ? 'Everything published on the audit tier has been signed off.'
              : 'No changes have been processed yet.'}
        </Empty>
      )}

      {rows?.length > 0 && (
        <div className="list">
          {rows.map(r => {
            const t = TIER[r.tier] ?? { tone: 'neutral', label: r.tier };
            return (
              <div className="card rise" key={r.id} style={{ padding: '19px 21px' }}>
                <div className="row-wrap" style={{ gap: 10, marginBottom: 10 }}>
                  <Badge tone={t.tone}>{t.label}</Badge>
                  {r.needs_audit && <Badge tone="warn">sign-off pending</Badge>}
                  <span className="spacer" />
                  <span className="faint mono" style={{ fontSize: 12.2 }}>
                    {new Date(r.created_at).toLocaleDateString(undefined, { day: 'numeric', month: 'short' })}
                  </span>
                </div>

                <div style={{ fontWeight: 600, fontSize: 15.4, lineHeight: 1.35 }}>{r.act_name}</div>
                <div className="faint" style={{ fontSize: 13, marginTop: 4, wordBreak: 'break-all' }}>{r.url}</div>

                <p className="muted" style={{ fontSize: 13.8, marginTop: 11, paddingLeft: 12, borderLeft: '2px solid var(--border-strong)', lineHeight: 1.55 }}>
                  {r.reason}
                </p>

                {r.status === 'pending' && (
                  <div className="row-wrap" style={{ gap: 9, marginTop: 15 }}>
                    <button className="btn btn-primary btn-sm"><Check size={15} /> Approve &amp; ingest</button>
                    <button className="btn btn-ghost btn-sm">Reject</button>
                    <span className="faint" style={{ fontSize: 12.4 }}>Approving runs the same ingestion pipeline as a manual run.</span>
                  </div>
                )}
                {r.needs_audit && r.status === 'published' && (
                  <div className="row-wrap" style={{ gap: 9, marginTop: 15 }}>
                    <button className="btn btn-ghost btn-sm"><Check size={15} /> Sign off</button>
                    <span className="faint" style={{ fontSize: 12.4 }}>Already live — signing off closes the audit flag.</span>
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}

      <div style={{ marginTop: 26 }}>
        <Disclaimer>
          Review actions are shown here for the corpus maintainer. In deployment these endpoints sit
          behind authentication — the reviewer identity recorded against a decision is only as
          trustworthy as the login behind it.
        </Disclaimer>
      </div>
    </div>
  );
}
