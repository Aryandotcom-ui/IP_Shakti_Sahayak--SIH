import { useState, useEffect } from 'react';
import { api } from '../lib/api.js';
import { useDemo } from '../App.jsx';
import { Doc, Clock, Check, Alert, Chevron } from '../components/Icons.jsx';
import { Badge, Empty, Disclaimer, Explain } from '../components/Bits.jsx';

/* The case lifecycle, shown as a pipeline so a first-time user can see
   where a case is and what happens next without reading documentation. */
const STAGES = [
  { key: 'intake',     label: 'Intake' },
  { key: 'prechecked', label: 'Pre-checked' },
  { key: 'drafted',    label: 'Forms drafted' },
  { key: 'handed_off', label: 'With agent' },
];

const STATUS_TONE = {
  intake: 'neutral', prechecked: 'info', drafted: 'warn', handed_off: 'ok',
  filed: 'ok', granted: 'ok', rejected: 'stop',
};

export default function Cases() {
  const [cases, setCases] = useState(null);
  const [selected, setSelected] = useState(null);
  const [deadlines, setDeadlines] = useState(null);
  const { setDemo } = useDemo();

  useEffect(() => {
    api.cases().then(r => {
      if (r.demo) setDemo(true);
      setCases(r.data);
      setSelected(r.data[0] ?? null);
    });
  }, [setDemo]);

  useEffect(() => {
    if (!selected) return;
    setDeadlines(null);
    api.caseDeadlines(selected.id).then(r => {
      if (r.demo) setDemo(true);
      setDeadlines(r.data);
    });
  }, [selected, setDemo]);

  return (
    <div className="shell">
      <div style={{ marginBottom: 26 }}>
        <span className="eyebrow">Patent cases</span>
        <h1 style={{ fontSize: 'clamp(30px, 4vw, 40px)', margin: '10px 0 10px' }}>
          From intake to your patent agent
        </h1>
        <p className="muted" style={{ fontSize: 16, maxWidth: '66ch' }}>
          Each case collects the facts once, runs the biodiversity and prior-art pre-checks against
          them, drafts the form content, and tracks the dates that follow.
        </p>
      </div>

      {!cases && <div className="skeleton" style={{ height: 220, borderRadius: 18 }} />}

      {cases?.length === 0 && (
        <Empty icon={<Doc size={26} />} title="No cases yet">
          A case is created the first time you take a question further than an answer.
        </Empty>
      )}

      {cases?.length > 0 && (
        <div style={{ display: 'grid', gridTemplateColumns: 'minmax(0,340px) minmax(0,1fr)', gap: 24, alignItems: 'start' }}
             className="cases-grid">
          <div className="list">
            {cases.map(c => (
              <button
                key={c.id}
                onClick={() => setSelected(c)}
                className="list-row"
                style={{
                  textAlign: 'left', cursor: 'pointer', width: '100%',
                  borderColor: selected?.id === c.id ? 'var(--brand)' : undefined,
                  boxShadow: selected?.id === c.id ? 'var(--shadow-md)' : undefined,
                }}
              >
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{ fontWeight: 600, fontSize: 14.8, lineHeight: 1.35 }}>
                    {c.intake.invention_title}
                  </div>
                  <div className="faint" style={{ fontSize: 13, marginTop: 4 }}>
                    {c.intake.applicant_name}
                  </div>
                  <div style={{ marginTop: 9 }}>
                    <Badge tone={STATUS_TONE[c.status] ?? 'neutral'}>
                      {c.status.replace(/_/g, ' ')}
                    </Badge>
                  </div>
                </div>
                <Chevron dir="down" size={16} style={{ transform: 'rotate(-90deg)', color: 'var(--text-faint)', flexShrink: 0 }} />
              </button>
            ))}
          </div>

          {selected && <CaseDetail c={selected} deadlines={deadlines} />}
        </div>
      )}
    </div>
  );
}

function CaseDetail({ c, deadlines }) {
  const stageIdx = STAGES.findIndex(s => s.key === c.status);
  return (
    <div style={{ display: 'grid', gap: 18 }} className="fade">
      <div className="card" style={{ padding: 24 }}>
        <h2 style={{ fontSize: 22, lineHeight: 1.25 }}>{c.intake.invention_title}</h2>
        <p className="muted" style={{ fontSize: 14.6, marginTop: 7 }}>
          {c.intake.applicant_name} · {c.intake.inventors?.join(', ')}
        </p>

        {/* Pipeline */}
        <div style={{ display: 'flex', gap: 0, marginTop: 24, alignItems: 'center' }}>
          {STAGES.map((s, i) => {
            const done = i <= stageIdx;
            return (
              <div key={s.key} style={{ flex: 1, display: 'flex', alignItems: 'center', minWidth: 0 }}>
                <div style={{ textAlign: 'center', flexShrink: 0 }}>
                  <div style={{
                    width: 30, height: 30, borderRadius: '50%', display: 'grid', placeItems: 'center',
                    margin: '0 auto 7px',
                    background: done ? 'var(--green-700)' : 'var(--bg-sunken)',
                    color: done ? '#fff' : 'var(--text-faint)',
                    border: `1px solid ${done ? 'var(--green-700)' : 'var(--border)'}`,
                    transition: 'all 240ms cubic-bezier(.2,.7,.3,1)',
                  }}>
                    {done ? <Check size={15} /> : <span style={{ fontSize: 12.5, fontWeight: 600 }}>{i + 1}</span>}
                  </div>
                  <div style={{ fontSize: 12.2, color: done ? 'var(--text)' : 'var(--text-faint)', fontWeight: done ? 600 : 400, whiteSpace: 'nowrap' }}>
                    {s.label}
                  </div>
                </div>
                {i < STAGES.length - 1 && (
                  <div style={{ flex: 1, height: 2, background: i < stageIdx ? 'var(--green-700)' : 'var(--border)', margin: '0 6px', marginBottom: 20 }} />
                )}
              </div>
            );
          })}
        </div>
      </div>

      <div className="card" style={{ padding: 24 }}>
        <h3 style={{ fontSize: 17, marginBottom: 14 }}>The facts on file</h3>
        <dl className="kv" style={{ marginTop: 0, gap: '10px 20px' }}>
          <dt>Formulation</dt><dd>{c.intake.formulation_type ?? '—'}</dd>
          <dt>Applicant</dt><dd>{(c.intake.applicant_category ?? '—').replace(/_/g, ' ')}</dd>
          <dt>Resource origin</dt><dd>{(c.intake.resource_origin ?? '—').replace(/_/g, ' ')}</dd>
          <dt>Collection</dt><dd>{(c.intake.resource_cultivation ?? '—').replace(/_/g, ' ')}</dd>
          <dt>Priority date</dt><dd className="mono">{c.intake.priority_date ?? '—'}</dd>
          <dt>Filing date</dt><dd className="mono">{c.intake.filing_date ?? 'not filed'}</dd>
        </dl>
      </div>

      <div className="card" style={{ padding: 24 }}>
        <div className="row-wrap" style={{ gap: 10, marginBottom: 6 }}>
          <h3 style={{ fontSize: 17 }}>Deadlines</h3>
          <Explain>
            Computed from the dates on file. Rules marked “unverified” are this system’s best
            understanding of a procedural deadline and must be confirmed against the amended Rules
            before you rely on them.
          </Explain>
        </div>
        <p className="muted" style={{ fontSize: 13.8, marginBottom: 16 }}>
          A deadline with no anchor date simply hasn’t started yet — it’s listed so you can see what
          the tracking is waiting on.
        </p>

        {!deadlines && <div className="skeleton" style={{ height: 130 }} />}

        {deadlines && (
          <div className="list">
            {deadlines.map(d => {
              const tone = d.status === 'overdue' ? 'stop'
                : d.status === 'due_soon' ? 'warn'
                : d.status === 'anchor_unknown' ? 'neutral' : 'ok';
              const color = tone === 'stop' ? 'var(--stop)' : tone === 'warn' ? 'var(--warn)' : tone === 'ok' ? 'var(--ok)' : 'var(--ink-300)';
              const pct = d.days_remaining == null ? 0
                : Math.max(6, Math.min(100, 100 - (d.days_remaining / 1100) * 100));
              return (
                <div className="dl" key={d.rule_id}>
                  <span className="dl-date" style={{ color: d.due_date ? 'var(--text)' : 'var(--text-faint)' }}>
                    {d.due_date ?? '—'}
                  </span>
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div style={{ fontSize: 14.4, fontWeight: 500, lineHeight: 1.35 }}>{d.label}</div>
                    <div className="faint mono" style={{ fontSize: 12.2, marginTop: 3 }}>
                      {d.legal_basis.act_name}, {d.legal_basis.section}
                    </div>
                    <div className="dl-bar" style={{ marginTop: 8 }}>
                      <span style={{ width: `${pct}%`, background: color }} />
                    </div>
                  </div>
                  <div style={{ textAlign: 'right', flexShrink: 0, display: 'grid', gap: 5, justifyItems: 'end' }}>
                    <Badge tone={tone}>
                      {d.status === 'anchor_unknown' ? 'not started'
                        : d.status === 'due_soon' ? `${d.days_remaining} days`
                        : d.status === 'overdue' ? 'overdue'
                        : `${d.days_remaining} days`}
                    </Badge>
                    {d.review_status === 'draft' && <Badge tone="warn">unverified</Badge>}
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </div>

      <div className="card" style={{ padding: 24 }}>
        <h3 style={{ fontSize: 17, marginBottom: 12 }}>Draft form content</h3>
        <div className="list">
          {[
            ['Form 1', 'Application for grant of patent', true],
            ['Form 3', 'Statement and undertaking under section 8', true],
            ['Form 27', 'Statement of working — only once granted', false],
          ].map(([id, desc, ready]) => (
            <div className="list-row" key={id}>
              <Doc size={18} style={{ color: ready ? 'var(--brand)' : 'var(--text-faint)', flexShrink: 0 }} />
              <div style={{ flex: 1, minWidth: 0 }}>
                <strong style={{ fontSize: 14.6, fontWeight: 600 }}>{id}</strong>
                <div className="faint" style={{ fontSize: 13.2, marginTop: 2 }}>{desc}</div>
              </div>
              <Badge tone={ready ? 'ok' : 'neutral'}>{ready ? 'drafted' : 'not applicable yet'}</Badge>
            </div>
          ))}
        </div>
        <div style={{ marginTop: 16 }}>
          <Disclaimer>
            Draft content is a preparation aid for a registered patent agent to transcribe onto the
            official form and verify — never file it as-is. Form 3’s foreign-filing disclosure is
            deliberately left blank: section 8 is strict-liability, and a guessed answer there can be
            fatal to the patent on its own.
          </Disclaimer>
        </div>
      </div>
    </div>
  );
}
