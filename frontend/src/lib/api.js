/**
 * Backend client for the IP-SAKTI Sahayak FastAPI service.
 *
 * Every call tries the real API first and falls back to sample data when
 * the backend is unreachable (nothing running, or corpus not yet ingested,
 * which returns 503). The fallback sets `demo: true` on the result, and the
 * UI surfaces that as a persistent banner — see lib/demo.js for why that
 * honesty is load-bearing rather than decorative.
 */

import {
  DEMO_ANSWER, DEMO_ABSTAIN, DEMO_CORPUS, DEMO_CASES,
  DEMO_DEADLINES, DEMO_REVIEW_QUEUE,
} from './demo.js';

const BASE = import.meta.env.VITE_API_BASE ?? '/api/v1';
const TIMEOUT_MS = 12000;

/** Fetch with a timeout — a hung backend must not hang the UI forever. */
async function req(path, { method = 'GET', body, signal } = {}) {
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), TIMEOUT_MS);
  if (signal) signal.addEventListener('abort', () => ctrl.abort(), { once: true });
  try {
    const res = await fetch(BASE + path, {
      method,
      headers: body ? { 'Content-Type': 'application/json' } : undefined,
      body: body ? JSON.stringify(body) : undefined,
      signal: ctrl.signal,
    });
    if (!res.ok) {
      const detail = await res.json().catch(() => ({}));
      const err = new Error(detail.detail || `${res.status} ${res.statusText}`);
      err.status = res.status;
      throw err;
    }
    return await res.json();
  } finally {
    clearTimeout(timer);
  }
}

/** Run `live`, falling back to `sample` on any transport/5xx failure. */
async function withFallback(live, sample) {
  try {
    return { data: await live(), demo: false };
  } catch (err) {
    if (err.name === 'AbortError') throw err;
    return { data: typeof sample === 'function' ? sample() : sample, demo: true, reason: err.message };
  }
}

export const api = {
  corpus: () => withFallback(() => req('/corpus'), DEMO_CORPUS),

  ask: ({ query, language, classification, complianceFacts, topK = 5, signal }) =>
    withFallback(
      () => req('/query', {
        method: 'POST',
        signal,
        body: {
          query,
          top_k: topK,
          language: language && language !== 'auto' ? language : null,
          classification: classification && Object.values(classification).some(Boolean)
            ? classification : null,
          compliance_facts: complianceFacts && Object.keys(complianceFacts).length
            ? complianceFacts : null,
          consent_licensed_acts: [],
        },
      }),
      // The sample answer is chosen to match the question's shape so the
      // demo never claims to have retrieved something it plainly did not.
      () => (looksUnanswerable(query) ? DEMO_ABSTAIN : { ...DEMO_ANSWER, language: language === 'auto' ? 'en' : language }),
    ),

  cases: () => withFallback(() => req('/patent-cases'), DEMO_CASES),
  caseDeadlines: (id) => withFallback(() => req(`/patent-cases/${id}/deadlines`), DEMO_DEADLINES),

  reviewPending: () => withFallback(() => req('/updates/pending'), DEMO_REVIEW_QUEUE.filter(r => r.status === 'pending')),
  reviewHistory: () => withFallback(() => req('/updates/history'), DEMO_REVIEW_QUEUE.filter(r => r.status !== 'pending')),
  reviewNeedsAudit: () => withFallback(() => req('/updates/needs-audit'), DEMO_REVIEW_QUEUE.filter(r => r.needs_audit)),
};

/**
 * Heuristic used only to pick which sample response to show offline, so a
 * question the corpus obviously cannot answer demos the abstention path
 * instead of inventing a confident answer for it.
 */
function looksUnanswerable(q) {
  const s = (q || '').toLowerCase();
  return /recipe|biryani|weather|cricket|stock price|who won|joke/.test(s);
}

export const LANGUAGES = [
  { code: 'auto', label: 'Detect', native: 'Auto' },
  { code: 'en', label: 'English', native: 'English' },
  { code: 'hi', label: 'Hindi', native: 'हिन्दी' },
  { code: 'mr', label: 'Marathi', native: 'मराठी' },
  { code: 'bn', label: 'Bengali', native: 'বাংলা' },
  { code: 'ta', label: 'Tamil', native: 'தமிழ்' },
  { code: 'te', label: 'Telugu', native: 'తెలుగు' },
  { code: 'kn', label: 'Kannada', native: 'ಕನ್ನಡ' },
  { code: 'ml', label: 'Malayalam', native: 'മലയാളം' },
  { code: 'gu', label: 'Gujarati', native: 'ગુજરાતી' },
  { code: 'pa', label: 'Punjabi', native: 'ਪੰਜਾਬੀ' },
];

export const FORMULATION_TYPES = [
  { value: 'classical', label: 'Classical', hint: 'Made to a formula in an authoritative classical text' },
  { value: 'proprietary', label: 'Proprietary', hint: 'Your own formulation, not from a classical text' },
  { value: 'phytopharmaceutical', label: 'Phytopharmaceutical', hint: 'Purified plant extract with defined constituents' },
  { value: 'new_drug', label: 'New drug', hint: 'Regulated as a new drug' },
  { value: 'aahar', label: 'Ayurveda Aahar', hint: 'Sold as a food, not a medicine' },
  { value: 'cosmetic', label: 'Cosmetic', hint: 'Sold as a cosmetic' },
];

export const APPLICANT_CATEGORIES = [
  { value: 'indian_individual', label: 'Indian citizen' },
  { value: 'indian_entity', label: 'Indian company' },
  { value: 'foreign_controlled_entity', label: 'Indian company, foreign-controlled' },
  { value: 'non_resident_indian', label: 'Non-resident Indian' },
  { value: 'foreign_national', label: 'Foreign national or company' },
];

export const RESOURCE_ORIGINS = [
  { value: 'india', label: 'From India' },
  { value: 'outside_india', label: 'Outside India' },
  { value: 'mixed', label: 'Both' },
];

export const CULTIVATION = [
  { value: 'cultivated', label: 'Cultivated' },
  { value: 'wild_collected', label: 'Wild-collected' },
  { value: 'mixed', label: 'Both' },
];
