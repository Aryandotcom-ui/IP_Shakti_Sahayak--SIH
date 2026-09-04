# IP-SAKTI Sahayak — frontend

React + Vite interface for the IP-SAKTI Sahayak backend.

```bash
npm install
npm run dev          # http://localhost:5173
```

Vite proxies `/api` to `http://localhost:8000` (override with
`VITE_API_TARGET`), so the browser sees one origin and CORS never comes
up in development. To point at a deployed API instead, set
`VITE_API_BASE=https://your-host/api/v1`.

## Screens

| Route | Purpose |
|---|---|
| `/` | Landing — explains the product in plain language for someone who has never heard of section 3(p) or ABS |
| `/ask` | The core: question → cited answer, confidence, retrieved text, compliance obligations, open questions |
| `/cases` | Patent-prep lifecycle: intake → pre-check → drafted forms → agent handoff, with deadline tracking |
| `/review` | The auto-update review gate: what changed upstream and what needs a human |

## Demo mode

Every API call falls back to sample data when the backend is unreachable
(nothing running, or `/corpus` returning 503 because no corpus has been
ingested yet). When that happens a **persistent, non-dismissible banner**
says so.

That banner is not decoration. This product's entire claim is that a
citation traces to real law — sample content presented as though it were
retrieved would be precisely the failure the system exists to prevent. If
you demo this without a backend, leave the banner up.

Sample fixtures live in `src/lib/demo.js` and mirror
`backend/app/schemas.py` field-for-field, so switching to the live API
changes nothing in the components.

## Design notes

- **Fonts are self-hosted** in `public/fonts` rather than loaded from the
  Google Fonts CDN — venue wifi shouldn't be a demo dependency, and it
  keeps first paint off the network. ~560 KB for Fraunces, Inter and Noto
  Sans Devanagari.
- **Provenance is the hero.** Confidence is a meter with a plain-language
  reading, not a bare number; every citation opens to the section text it
  came from; abstention is a first-class state with its own dignified
  treatment, not an error.
- **Terms of art are explained inline.** Small `i` markers cover
  abstention, ABS, TKDL, unverified deadline rules — a vaidya arriving
  here does not know these and shouldn't have to.
- Light and dark themes, `prefers-reduced-motion` respected, keyboard
  focus visible throughout.

## Known gaps

- Review-gate and case actions (approve / reject / sign off) are wired to
  the UI but not yet POSTing — those endpoints need authentication in
  front of them first.
- No auth flow; `decided_by` on the backend is unverified free text.
- Case creation and intake editing aren't built yet; `/cases` reads
  existing cases only.
