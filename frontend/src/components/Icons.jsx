/** Inline SVG icons — stroke-based, inherit currentColor, 1.7px weight. */
const s = { fill: 'none', stroke: 'currentColor', strokeWidth: 1.7, strokeLinecap: 'round', strokeLinejoin: 'round' };

export const Leaf = ({ size = 22, ...p }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" {...s} {...p}>
    <path d="M11 20A7 7 0 0 1 9.8 6.1C15.5 5 17 4.48 19 2c1 2 2 4.18 2 8 0 5.5-4.78 10-10 10Z" />
    <path d="M2 21c0-3 1.85-5.36 5.08-6C9.5 14.52 12 13 13 12" />
  </svg>
);

export const Scale = ({ size = 22, ...p }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" {...s} {...p}>
    <path d="M12 3v18M8 21h8M3 7h18M7 7l-4 7h8ZM17 7l-4 7h8Z" />
  </svg>
);

export const Shield = ({ size = 22, ...p }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" {...s} {...p}>
    <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10Z" />
    <path d="m9 12 2 2 4-4" />
  </svg>
);

export const Doc = ({ size = 22, ...p }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" {...s} {...p}>
    <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8Z" />
    <path d="M14 2v6h6M8 13h8M8 17h5" />
  </svg>
);

export const Search = ({ size = 22, ...p }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" {...s} {...p}>
    <circle cx="11" cy="11" r="7" /><path d="m20 20-3.5-3.5" />
  </svg>
);

export const Send = ({ size = 18, ...p }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" {...s} {...p}>
    <path d="M22 2 11 13M22 2l-7 20-4-9-9-4Z" />
  </svg>
);

export const Chevron = ({ size = 18, dir = 'down', ...p }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" {...s} {...p}
    style={{ transition: 'transform 240ms cubic-bezier(.2,.7,.3,1)', transform: dir === 'up' ? 'rotate(180deg)' : 'none' }}>
    <path d="m6 9 6 6 6-6" />
  </svg>
);

export const Clock = ({ size = 18, ...p }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" {...s} {...p}>
    <circle cx="12" cy="12" r="9" /><path d="M12 7v5l3 2" />
  </svg>
);

export const Alert = ({ size = 20, ...p }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" {...s} {...p}>
    <path d="M10.3 3.9 1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0Z" />
    <path d="M12 9v4M12 17h.01" />
  </svg>
);

export const Info = ({ size = 20, ...p }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" {...s} {...p}>
    <circle cx="12" cy="12" r="9" /><path d="M12 16v-4M12 8h.01" />
  </svg>
);

export const Check = ({ size = 18, ...p }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" {...s} {...p}><path d="m4 12 5 5L20 6" /></svg>
);

export const Globe = ({ size = 18, ...p }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" {...s} {...p}>
    <circle cx="12" cy="12" r="9" /><path d="M3 12h18M12 3a15 15 0 0 1 0 18 15 15 0 0 1 0-18Z" />
  </svg>
);

export const Sun = ({ size = 18, ...p }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" {...s} {...p}>
    <circle cx="12" cy="12" r="4" />
    <path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4" />
  </svg>
);

export const Moon = ({ size = 18, ...p }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" {...s} {...p}>
    <path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8Z" />
  </svg>
);

export const Flask = ({ size = 22, ...p }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" {...s} {...p}>
    <path d="M9 3h6M10 3v6.5L4.6 18a2 2 0 0 0 1.7 3h11.4a2 2 0 0 0 1.7-3L14 9.5V3" />
    <path d="M7 15h10" />
  </svg>
);

export const Refresh = ({ size = 18, ...p }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" {...s} {...p}>
    <path d="M21 12a9 9 0 1 1-2.6-6.4M21 3v6h-6" />
  </svg>
);
