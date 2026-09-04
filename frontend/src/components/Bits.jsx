import { useState, useRef, useEffect } from 'react';
import { Chevron, Info } from './Icons.jsx';

/** Small explanatory tooltip — this product is full of terms of art
 *  (abstention, ABS, TKDL) that a first-time user will not know. */
export function Explain({ children }) {
  const [open, setOpen] = useState(false);
  return (
    <span style={{ position: 'relative', display: 'inline-block' }}>
      <span
        className="info-dot"
        tabIndex={0}
        role="button"
        aria-label="What does this mean?"
        onMouseEnter={() => setOpen(true)}
        onMouseLeave={() => setOpen(false)}
        onFocus={() => setOpen(true)}
        onBlur={() => setOpen(false)}
      >i</span>
      {open && (
        <span
          role="tooltip"
          className="fade"
          style={{
            position: 'absolute', bottom: 'calc(100% + 9px)', left: '50%',
            transform: 'translateX(-50%)', width: 260, zIndex: 60,
            background: 'var(--ink-900)', color: 'var(--paper)',
            padding: '11px 13px', borderRadius: 10, fontSize: 13,
            lineHeight: 1.5, fontWeight: 400, boxShadow: 'var(--shadow-lg)',
            textTransform: 'none', letterSpacing: 0,
          }}
        >{children}</span>
      )}
    </span>
  );
}

/** Accordion with a measured height transition (no layout jank). */
export function Disclose({ title, meta, children, defaultOpen = false, className = '' }) {
  const [open, setOpen] = useState(defaultOpen);
  const inner = useRef(null);
  const [h, setH] = useState(defaultOpen ? 'auto' : 0);

  useEffect(() => {
    if (!inner.current) return;
    setH(open ? inner.current.scrollHeight : 0);
  }, [open, children]);

  return (
    <div className={className}>
      <button className="source-head" aria-expanded={open} onClick={() => setOpen(o => !o)}>
        <Chevron dir={open ? 'up' : 'down'} size={17} style={{ color: 'var(--text-faint)', flexShrink: 0 }} />
        <span style={{ flex: 1, minWidth: 0 }}>{title}</span>
        {meta}
      </button>
      <div style={{ height: h, overflow: 'hidden', transition: 'height 260ms cubic-bezier(.2,.7,.3,1)' }}>
        <div ref={inner} className="source-body">{children}</div>
      </div>
    </div>
  );
}

/** Confidence as a visible meter. The number alone means nothing to a
 *  non-specialist, so it is always paired with a plain-language reading. */
export function Confidence({ value, abstained }) {
  const pct = Math.round((value ?? 0) * 100);
  const band = abstained ? 'low' : pct >= 70 ? 'high' : pct >= 45 ? 'medium' : 'low';
  const color = band === 'high' ? 'var(--ok)' : band === 'medium' ? 'var(--warn)' : 'var(--stop)';
  const note = {
    high: 'Strong match against the cited sources.',
    medium: 'Partial match — read the sources before relying on this.',
    low: 'Too weak to answer from. Treat nothing here as settled.',
  }[band];

  return (
    <div className="conf">
      <div className="conf-top">
        <span className="conf-label">
          Confidence
          <Explain>
            How closely the retrieved law matches your question — not how correct the answer is.
            Below the threshold the system abstains instead of guessing.
          </Explain>
        </span>
        <span className="conf-val" style={{ color }}>{pct}%</span>
      </div>
      <div className="conf-track">
        <div className="conf-fill" style={{ width: `${Math.max(pct, 2)}%`, background: color }} />
      </div>
      <p className="conf-note">{note}</p>
    </div>
  );
}

export function Badge({ tone = 'neutral', children, ...p }) {
  return <span className={`badge badge-${tone}`} {...p}>{children}</span>;
}

export function Chip({ active, children, ...p }) {
  return <button type="button" className="chip" aria-pressed={!!active} {...p}>{children}</button>;
}

export function Empty({ icon, title, children }) {
  return (
    <div className="empty">
      <div className="empty-ico">{icon}</div>
      <h3 style={{ fontSize: 19, marginBottom: 8 }}>{title}</h3>
      <p className="muted" style={{ maxWidth: '46ch', margin: '0 auto', fontSize: 14.6 }}>{children}</p>
    </div>
  );
}

export function Disclaimer({ children }) {
  return (
    <div className="disclaimer">
      <Info size={17} style={{ flexShrink: 0, marginTop: 1, color: 'var(--text-faint)' }} />
      <span>{children}</span>
    </div>
  );
}
