import { useState, useRef, useEffect } from 'react';
import {
  api, LANGUAGES, FORMULATION_TYPES, APPLICANT_CATEGORIES,
  RESOURCE_ORIGINS, CULTIVATION,
} from '../lib/api.js';
import { useDemo } from '../App.jsx';
import {
  Send, Search, Chevron, Alert, Info, Check, Clock, Globe, Scale,
} from '../components/Icons.jsx';
import {
  Confidence, Disclose, Badge, Chip, Explain, Empty, Disclaimer,
} from '../components/Bits.jsx';

const EXAMPLES = [
  'Can a classical Ayurvedic formulation be patented in India?',
  'Do I need NBA approval if I use a wild-collected herb?',
  'क्या पारंपरिक फ़ॉर्मूलेशन का पेटेंट हो सकता है?',
  'What must I disclose about the origin of my plant material?',
];

export default function Ask() {
  const [q, setQ] = useState('');
  const [lang, setLang] = useState('auto');
  const [openFacts, setOpenFacts] = useState(false);
  const [facts, setFacts] = useState({});
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState(null);
  const { setDemo } = useDemo();
  const resultRef = useRef(null);
  const taRef = useRef(null);

  // Autosize the composer rather than making the user scroll a 3-line box.
  useEffect(() => {
    const ta = taRef.current;
    if (!ta) return;
    ta.style.height = 'auto';
    ta.style.height = Math.min(ta.scrollHeight, 220) + 'px';
  }, [q]);

  const set = (k, v) => setFacts(f => ({ ...f, [k]: f[k] === v ? undefined : v }));

  async function submit(e) {
    e?.preventDefault();
    const query = q.trim();
    if (query.length < 3 || loading) return;
    setLoading(true);
    setResult(null);

    const { formulation_type, ...rest } = facts;
    const complianceFacts = Object.fromEntries(
      Object.entries(rest).filter(([, v]) => v !== undefined)
    );

    const res = await api.ask({
      query,
      language: lang,
      classification: { formulation_type, jurisdiction: 'india' },
      complianceFacts,
    });

    if (res.demo) setDemo(true);
    setResult(res.data);
    setLoading(false);
    requestAnimationFrame(() =>
      resultRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' })
    );
  }

  return (
    <div className="shell" style={{ maxWidth: 940 }}>
      <div style={{ marginBottom: 26 }}>
        <span className="eyebrow">Ask</span>
        <h1 style={{ fontSize: 'clamp(30px, 4vw, 40px)', margin: '10px 0 10px' }}>
          What would you like to know?
        </h1>
        <p className="muted" style={{ fontSize: 16, maxWidth: '62ch' }}>
          Ask in plain words, in your own language. You’ll get the answer, the sections it rests on,
          and any compliance duties your facts trigger.
        </p>
      </div>

      <form onSubmit={submit}>
        <div className="composer">
          <textarea
            ref={taRef}
            rows={2}
            value={q}
            onChange={e => setQ(e.target.value)}
            onKeyDown={e => { if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) submit(e); }}
            placeholder="e.g. Can I patent a formulation based on a classical text if I've changed the extraction process?"
            aria-label="Your question"
          />
          <div className="composer-bar">
            <span className="row faint" style={{ gap: 6, fontSize: 13 }}>
              <Globe size={15} /> Language
            </span>
            <select className="select" value={lang} onChange={e => setLang(e.target.value)} aria-label="Question language">
              {LANGUAGES.map(l => (
                <option key={l.code} value={l.code}>{l.native}</option>
              ))}
            </select>
            <span className="spacer" />
            <span className="faint" style={{ fontSize: 12.5 }}>⌘↵ to send</span>
            <button type="submit" className="btn btn-primary btn-sm" disabled={q.trim().length < 3 || loading}>
              {loading ? 'Searching…' : <>Ask <Send size={16} /></>}
            </button>
          </div>
        </div>
      </form>

      {!result && !loading && (
        <div className="examples">
          {EXAMPLES.map(ex => (
            <button key={ex} className="example" onClick={() => { setQ(ex); taRef.current?.focus(); }}>
              {ex}
            </button>
          ))}
        </div>
      )}

      {/* Optional facts. Collapsed by default so the empty state stays
          inviting, but flagged as the thing that sharpens the answer. */}
      <div className="panel" style={{ marginTop: 18 }}>
        <button className="panel-head" aria-expanded={openFacts} onClick={() => setOpenFacts(o => !o)}>
          <Chevron dir={openFacts ? 'up' : 'down'} size={17} style={{ color: 'var(--text-faint)' }} />
          <span style={{ flex: 1 }}>
            <strong style={{ fontSize: 15, fontWeight: 600 }}>Tell it about your formulation</strong>
            <span className="faint" style={{ display: 'block', fontSize: 13.2, marginTop: 2 }}>
              Optional — but these are the facts that decide whether a biodiversity duty applies to you.
            </span>
          </span>
          {Object.values(facts).filter(Boolean).length > 0 && (
            <Badge tone="ok">{Object.values(facts).filter(Boolean).length} set</Badge>
          )}
        </button>

        {openFacts && (
          <div className="panel-body fade">
            <FactRow
              label="What kind of formulation is it?"
              hint="Classical means made to a formula set out in an authoritative classical text."
              options={FORMULATION_TYPES}
              value={facts.formulation_type}
              onPick={v => set('formulation_type', v)}
            />
            <FactRow
              label="Who is applying?"
              hint="Whether the applicant is a section 3(2) person changes which approval route applies."
              options={APPLICANT_CATEGORIES}
              value={facts.applicant_category}
              onPick={v => set('applicant_category', v)}
            />
            <FactRow
              label="Where did the biological material come from?"
              options={RESOURCE_ORIGINS}
              value={facts.resource_origin}
              onPick={v => set('resource_origin', v)}
            />
            <FactRow
              label="Was it cultivated or wild-collected?"
              hint="Cultivated medicinal plants can fall under a section 40 exemption; wild-collected generally do not."
              options={CULTIVATION}
              value={facts.resource_cultivation}
              onPick={v => set('resource_cultivation', v)}
            />
          </div>
        )}
      </div>

      <div ref={resultRef} style={{ scrollMarginTop: 88 }}>
        {loading && <Thinking />}
        {result && !loading && <Answer data={result} />}
      </div>

      {!result && !loading && (
        <div style={{ marginTop: 40 }}>
          <Empty icon={<Search size={26} />} title="Nothing asked yet">
            Pick one of the examples above, or type your own question. Answers always come with the
            sections they rest on — and an honest “I can’t tell” when the corpus doesn’t cover it.
          </Empty>
        </div>
      )}
    </div>
  );
}

function FactRow({ label, hint, options, value, onPick }) {
  return (
    <div className="field">
      <span className="field-label">{label}</span>
      <div className="seg">
        {options.map(o => (
          <Chip key={o.value} active={value === o.value} onClick={() => onPick(o.value)} title={o.hint}>
            {o.label}
          </Chip>
        ))}
      </div>
      {hint && <p className="field-hint">{hint}</p>}
    </div>
  );
}

function Thinking() {
  const steps = ['Detecting language', 'Retrieving matching law', 'Screening obligations', 'Composing the answer'];
  const [i, setI] = useState(0);
  useEffect(() => {
    const t = setInterval(() => setI(n => Math.min(n + 1, steps.length - 1)), 620);
    return () => clearInterval(t);
  }, []);
  return (
    <div className="card fade" style={{ marginTop: 26 }}>
      <div className="thinking">
        <span className="pulse" />
        <span style={{ fontSize: 15, fontWeight: 500 }}>{steps[i]}…</span>
      </div>
      <div style={{ padding: '0 24px 24px', display: 'grid', gap: 10 }}>
        <div className="skeleton" style={{ height: 13, width: '92%' }} />
        <div className="skeleton" style={{ height: 13, width: '86%' }} />
        <div className="skeleton" style={{ height: 13, width: '64%' }} />
      </div>
    </div>
  );
}

function Answer({ data }) {
  const c = data.compliance;
  const blocking = c?.obligations?.filter(o => o.blocks_grant) ?? [];

  return (
    <div style={{ marginTop: 28, display: 'grid', gap: 22 }}>
      <div className="answer-card rise">
        <div className="answer-head">
          <div style={{ flex: 1, minWidth: 220 }}>
            <span className="eyebrow">Answer</span>
            <div className="row-wrap" style={{ marginTop: 9, gap: 8 }}>
              {data.abstained
                ? <Badge tone="info">Abstained</Badge>
                : <Badge tone="ok"><Check size={14} /> Answered</Badge>}
              {blocking.length > 0 && <Badge tone="stop">{blocking.length} blocking duties</Badge>}
              {data.language && data.language !== 'en' && (
                <Badge tone="neutral"><Globe size={13} /> {data.language.toUpperCase()}</Badge>
              )}
              {data.translated === false && <Badge tone="warn">Not translated</Badge>}
              {data.generation === 'mock' && (
                <Badge tone="warn">
                  Canned prose — no API key
                  <Explain>
                    The retrieved sections, citations and compliance screening below are
                    real. Only the wording of the answer is a deterministic stand-in,
                    because no ANTHROPIC_API_KEY is configured. Set one to get a
                    generated answer.
                  </Explain>
                </Badge>
              )}
            </div>
          </div>
          <Confidence value={data.confidence} abstained={data.abstained} />
        </div>

        <div className="answer-body">
          {data.abstained ? (
            <div className="abstain">
              <Info size={21} style={{ color: 'var(--info)', flexShrink: 0, marginTop: 2 }} />
              <div>
                <h4>The corpus doesn’t clearly answer this</h4>
                <p>
                  Rather than assemble a confident-sounding paragraph from weak matches, the system
                  stops here. Try narrowing the question, or adding your formulation details above —
                  that often brings the right provisions into range.
                </p>
              </div>
            </div>
          ) : (
            <div className="answer-text">
              {data.answer_text.split('\n\n').map((p, i) => <p key={i}>{p}</p>)}
            </div>
          )}
        </div>
      </div>

      {data.citations?.length > 0 && (
        <Section title="What this rests on" sub="Each citation is a section actually retrieved — open a source to read it.">
          <div className="cite-list">
            {data.citations.map((ct, i) => {
              const src = data.sources?.find(s => s.act_name === ct.act_name && s.section === ct.section);
              // Whether the Act's text is in the corpus is decided by the
              // graph's own coverage check, not by whether we happen to hold
              // a public URL for it. Most ingested Acts have no source_url
              // (the official sites are not reliably linkable), so keying
              // "not ingested" off the URL libelled 13 of the 17 documents
              // that are, in fact, fully ingested.
              const uncitable = (data.compliance?.uncitable_acts || []).some(
                u => (typeof u === 'string' ? u : u?.act_name) === ct.act_name,
              );
              const Wrapper = ct.source_url ? 'a' : 'div';
              return (
                <Wrapper
                  key={`${ct.act_name}-${ct.section}-${i}`}
                  className="cite"
                  {...(ct.source_url ? { href: ct.source_url, target: '_blank', rel: 'noreferrer' } : {})}
                >
                  <span className="cite-n">{i + 1}</span>
                  <span style={{ minWidth: 0, flex: 1 }}>
                    <span className="cite-act">{ct.act_name}</span>
                    <span className="cite-sec">
                      {ct.section}
                      {src && <> · match {(src.similarity_score * 100).toFixed(0)}%</>}
                      {uncitable
                        ? <> · <span title="This Act is named by the compliance graph but its text is not in the corpus, so the wording above cannot be checked against it">text not in corpus</span></>
                        : !ct.source_url && <> · <span title="This section was retrieved from the ingested text; we just hold no public URL to link out to">no public link</span></>}
                    </span>
                  </span>
                </Wrapper>
              );
            })}
          </div>
        </Section>
      )}

      {data.sources?.length > 0 && (
        <Section title="The retrieved text" sub="Verbatim, so you can judge the answer instead of trusting it.">
          <div className="list">
            {data.sources.map(s => (
              <Disclose
                key={s.chunk_id}
                className="source"
                title={<><strong style={{ fontWeight: 600, fontSize: 14.6 }}>{s.act_name}</strong>
                  <span className="faint" style={{ fontSize: 13.4 }}> · {s.section}</span></>}
                meta={<span className="score">{(s.similarity_score * 100).toFixed(0)}%</span>}
              >
                {s.text}
              </Disclose>
            ))}
          </div>
        </Section>
      )}

      {c && (
        <Section
          title="Compliance screening"
          sub={c.headline}
          badge={c.provisional ? <Badge tone="warn">Provisional · {Math.round(c.completeness * 100)}% complete</Badge> : null}
        >
          <div style={{ display: 'grid', gap: 12 }}>
            {c.obligations?.map(o => <Obligation key={o.id} o={o} />)}

            {c.inapplicable?.length > 0 && (
              <Disclose
                className="source"
                title={<span style={{ fontSize: 14.4 }}>Exemptions considered and <strong>not</strong> applied ({c.inapplicable.length})</span>}
                defaultOpen={false}
              >
                {c.inapplicable.map((x, i) => (
                  <div key={i} style={{ marginBottom: i < c.inapplicable.length - 1 ? 14 : 0 }}>
                    <strong style={{ fontWeight: 600, fontSize: 14.4, color: 'var(--text)' }}>{x.label}</strong>
                    <div className="mono faint" style={{ marginTop: 3 }}>{x.citation}</div>
                    <p style={{ marginTop: 6 }}>{x.note}</p>
                  </div>
                ))}
              </Disclose>
            )}

            {c.prior_art && (
              <div className="card" style={{ padding: '17px 19px' }}>
                <div className="row-wrap" style={{ gap: 10, marginBottom: 9 }}>
                  <Scale size={17} style={{ color: 'var(--text-faint)' }} />
                  <strong style={{ fontSize: 15, fontWeight: 600 }}>Prior-art exposure</strong>
                  <Badge tone={c.prior_art.risk === 'unknown' ? 'neutral' : c.prior_art.risk === 'medium' ? 'warn' : c.prior_art.risk === 'high' ? 'stop' : 'ok'}>
                    {c.prior_art.risk} risk
                  </Badge>
                  <Explain>
                    Checked against a traditional-knowledge index. A formulation already documented
                    there will be cited against your application under section 3(p).
                  </Explain>
                </div>
                <p className="muted" style={{ fontSize: 14.4, lineHeight: 1.6 }}>{c.prior_art.message}</p>
                {c.prior_art.hits?.length > 0 && (
                  <div style={{ marginTop: 11, display: 'grid', gap: 7 }}>
                    {c.prior_art.hits.map((h, i) => (
                      <div key={i} className="row" style={{ gap: 9, fontSize: 13.6 }}>
                        <Alert size={14} style={{ color: 'var(--warn)', flexShrink: 0 }} />
                        <strong style={{ fontWeight: 600 }}>{h.title}</strong>
                        <span className="faint">· {h.source}</span>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            )}

            {c.open_questions?.length > 0 && (
              <div style={{ display: 'grid', gap: 9 }}>
                <p className="eyebrow" style={{ marginTop: 6 }}>
                  Still needed to be sure
                  <Explain>
                    These facts decide whether a duty applies. Until they’re answered the screening is
                    marked provisional — an unanswered question is never read as “no obligation”.
                  </Explain>
                </p>
                {c.open_questions.map(qq => (
                  <div className="question" key={qq.field}>
                    <span className={`q-mark${qq.importance === 'critical' ? '' : ' clarifying'}`}>?</span>
                    <div>
                      <p style={{ fontSize: 14.6, lineHeight: 1.5 }}>{qq.question}</p>
                      <span className="faint" style={{ fontSize: 12.4 }}>
                        {qq.importance === 'critical' ? 'Decides a blocking obligation' : 'Refines the result'}
                      </span>
                    </div>
                  </div>
                ))}
              </div>
            )}

            <Disclaimer>{c.disclaimer}</Disclaimer>
          </div>
        </Section>
      )}

      <div className="row-wrap faint" style={{ fontSize: 12.6, gap: 14, paddingTop: 4 }}>
        <span>{data.disclaimer}</span>
        {data.audit_id && <span className="mono">audit · {data.audit_id}</span>}
      </div>
    </div>
  );
}

function Obligation({ o }) {
  const tone = o.blocks_grant ? 'blocking' : o.severity === 'mandatory' ? 'mandatory' : '';
  return (
    <div className={`oblig ${tone}`}>
      <div className="oblig-head">
        <div style={{ flex: 1, minWidth: 0 }}>
          <div className="oblig-title">{o.label}</div>
          <div className="oblig-meta">
            {o.blocks_grant && <Badge tone="stop">Blocks grant</Badge>}
            <Badge tone={o.severity === 'mandatory' ? 'warn' : 'neutral'}>{o.severity}</Badge>
            {o.form && <Badge tone="neutral">{o.form}</Badge>}
            {o.review_status === 'draft' && <Badge tone="warn">Unverified rule</Badge>}
          </div>
        </div>
      </div>
      <div className="oblig-body">
        <p className="oblig-rationale">{o.rationale}</p>
        {o.amendment_note && (
          <p className="oblig-rationale" style={{ marginTop: 10, paddingLeft: 12, borderLeft: '2px solid var(--warn)' }}>
            <strong style={{ color: 'var(--warn)', fontWeight: 600 }}>Amendment note. </strong>
            {o.amendment_note}
          </p>
        )}
        <dl className="kv">
          <dt>Basis</dt><dd className="mono">{o.citation}</dd>
          {o.authority && <><dt>File with</dt><dd>{o.authority}</dd></>}
          {o.deadline && <><dt>When</dt><dd><span className="row" style={{ gap: 6 }}><Clock size={14} style={{ color: 'var(--text-faint)' }} />{o.deadline}</span></dd></>}
        </dl>
      </div>
    </div>
  );
}

function Section({ title, sub, badge, children }) {
  return (
    <section className="rise">
      <div style={{ marginBottom: 14 }}>
        <div className="row-wrap" style={{ gap: 10 }}>
          <h2 style={{ fontSize: 21 }}>{title}</h2>
          {badge}
        </div>
        {sub && <p className="muted" style={{ fontSize: 14.4, marginTop: 5, maxWidth: '70ch' }}>{sub}</p>}
      </div>
      {children}
    </section>
  );
}
