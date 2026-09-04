/**
 * Sample responses used when the backend is unreachable.
 *
 * These mirror backend/app/schemas.py field-for-field, so switching to the
 * live API changes nothing in the components.
 *
 * IMPORTANT: every screen that renders this data shows a persistent
 * "sample data" banner. This project's whole premise is that a citation
 * must be traceable to real law — presenting invented legal content as
 * genuine would be the exact failure it exists to prevent. The sample
 * content below is illustrative of the shape of an answer, not a
 * statement of law.
 */

export const DEMO_CORPUS = { collection: 'ip_sakti_corpus', chunks: 0 };

const DISCLAIMER = 'This is informational, not legal advice.';

export const DEMO_ANSWER = {
  answer_text:
    'A classical Ayurvedic formulation described in an authoritative text is very unlikely to be patentable as such. Section 3(p) of the Patents Act, 1970 excludes an invention that is, in effect, traditional knowledge, or an aggregation or duplication of the known properties of a traditionally known component.\n\nWhat can still be patentable is a genuine technical advance over that traditional base — a novel extraction process, a demonstrated synergistic effect that is not merely additive, or a new delivery system — provided novelty and inventive step are established against the traditional knowledge itself, not just against patent literature.\n\nSeparately, if the formulation uses a biological resource obtained from India, approval under the Biological Diversity Act, 2002 is required before the intellectual property right is granted. That obligation is independent of whether the claim survives section 3(p).',
  citations: [
    { act_name: 'The Patents Act, 1970', section: 'Section 3(p)', source_url: 'https://www.indiacode.nic.in/handle/123456789/1979' },
    { act_name: 'The Patents Act, 1970', section: 'Section 3(d)', source_url: 'https://www.indiacode.nic.in/handle/123456789/1979' },
    { act_name: 'The Biological Diversity Act, 2002', section: 'Section 6', source_url: null },
  ],
  confidence: 0.83,
  abstained: false,
  disclaimer: DISCLAIMER,
  sources: [
    {
      chunk_id: 'the-patents-act-1970--s3',
      act_name: 'The Patents Act, 1970',
      section: 'Section 3(p)',
      jurisdiction: 'india',
      similarity_score: 0.87,
      source_url: 'https://www.indiacode.nic.in/handle/123456789/1979',
      text: 'The Patents Act, 1970 — Section 3: What are not inventions\n\n(p) an invention which, in effect, is traditional knowledge or which is an aggregation or duplication of known properties of traditionally known component or components.',
    },
    {
      chunk_id: 'the-patents-act-1970--s3d',
      act_name: 'The Patents Act, 1970',
      section: 'Section 3(d)',
      jurisdiction: 'india',
      similarity_score: 0.74,
      source_url: 'https://www.indiacode.nic.in/handle/123456789/1979',
      text: 'The mere discovery of a new form of a known substance which does not result in the enhancement of the known efficacy of that substance is not an invention within the meaning of this Act.',
    },
    {
      chunk_id: 'the-biological-diversity-act-2002--s6',
      act_name: 'The Biological Diversity Act, 2002',
      section: 'Section 6',
      jurisdiction: 'india',
      similarity_score: 0.69,
      source_url: null,
      text: 'No person shall apply for any intellectual property right, by whatever name called, in or outside India for any invention based on any research or information on a biological resource obtained from India without obtaining the previous approval of the National Biodiversity Authority.',
    },
  ],
  compliance: {
    triggered: true,
    headline: '2 obligation(s) must be discharged before the IP right can be granted.',
    regimes: ['Access and Benefit Sharing (biodiversity)', 'Patents and disclosure', 'Defensive protection of traditional knowledge'],
    obligations: [
      {
        id: 'nba_approval_before_grant',
        label: 'Obtain National Biodiversity Authority approval before grant of the IP right',
        act_name: 'The Biological Diversity Act, 2002',
        section: 'Section 6(1)',
        citation: 'The Biological Diversity Act, 2002, s. 6(1)',
        authority: 'National Biodiversity Authority (NBA)',
        deadline: 'Before grant of the IP right',
        deadline_anchor: 'ipr_grant',
        form: 'Form III',
        severity: 'mandatory',
        blocks_grant: true,
        rationale: 'The applicant is seeking an IP right over an invention based on a biological resource obtained from India, which engages section 6.',
        amendment_note: 'The Biological Diversity (Amendment) Act, 2023 moved this from approval before FILING to approval before GRANT. Applications pending across that change are assessed on the amended rule.',
        depends_on: [],
        review_status: 'reviewed',
        path: ['classical', 'biodiversity_abs', 'nba_approval_before_grant'],
      },
      {
        id: 'disclose_source_and_origin',
        label: 'Disclose the source and geographical origin of the biological material in the specification',
        act_name: 'The Patents Act, 1970',
        section: 'Section 10(4)(d)(ii)(D)',
        citation: 'The Patents Act, 1970, s. 10(4)(d)(ii)(D)',
        authority: 'Controller General of Patents, Designs and Trade Marks',
        deadline: 'At the time of filing the complete specification',
        deadline_anchor: 'ipr_filing',
        form: 'Form 1',
        severity: 'mandatory',
        blocks_grant: true,
        rationale: 'A complete specification for an invention using biological material must disclose its source and geographical origin; non-disclosure is a ground for both pre-grant and post-grant opposition.',
        amendment_note: '',
        depends_on: [],
        review_status: 'reviewed',
        path: ['classical', 'patents', 'disclose_source_and_origin'],
      },
      {
        id: 'tkdl_prior_art_check',
        label: 'Check the formulation against the Traditional Knowledge Digital Library before filing',
        act_name: 'The Patents Act, 1970',
        section: 'Section 3(p)',
        citation: 'The Patents Act, 1970, s. 3(p)',
        authority: 'Traditional Knowledge Digital Library (CSIR / Ministry of AYUSH)',
        deadline: 'Before filing',
        deadline_anchor: 'ipr_filing',
        form: null,
        severity: 'recommended',
        blocks_grant: false,
        rationale: 'A formulation already documented in TKDL will be cited against the application as prior art. Checking first is cheaper than a refusal.',
        amendment_note: '',
        depends_on: [],
        review_status: 'reviewed',
        path: ['classical', 'tk_defensive', 'tkdl_prior_art_check'],
      },
    ],
    exemptions: [],
    inapplicable: [
      {
        label: 'Cultivated medicinal plants and their products',
        citation: 'The Biological Diversity Act, 2002, s. 40',
        note: 'Section 40 lets the Central Government exempt normally traded commodities. It does not apply here because the resource was recorded as wild-collected.',
        covers: ['nba_approval_before_grant'],
        review_status: 'reviewed',
      },
    ],
    prior_art: {
      backend: 'local-classical-index',
      available: true,
      risk: 'medium',
      message: 'One documented classical formulation shares two of the three named ingredients. Verify against the full TKDL record before filing.',
      searched_terms: ['ashwagandha', 'turmeric', 'guduchi'],
      hits: [
        { title: 'Ashwagandharishta', source: 'Classical formulary (local index)', score: 0.71 },
      ],
    },
    open_questions: [
      { field: 'resource_cultivation', question: 'Was the biological resource cultivated or wild-collected?', importance: 'critical' },
      { field: 'intends_commercialisation', question: 'Do you intend to commercialise the resource or the resulting product?', importance: 'clarifying' },
    ],
    uncitable_acts: ['The Biological Diversity Act, 2002'],
    completeness: 0.78,
    provisional: true,
    disclaimer:
      'Automated regulatory screening, not legal advice. Every obligation above must be confirmed against the bare text of the cited provision and with a registered patent agent or counsel before it is acted on.',
  },
  licensed_sources_withheld: [],
  audit_id: 'demo-0000-0000-0000',
  language: 'en',
  translated: true,
};

export const DEMO_ABSTAIN = {
  ...DEMO_ANSWER,
  answer_text:
    "The provided sources do not clearly answer this question, so I can't provide a reliable answer here.",
  citations: [],
  sources: [],
  confidence: 0.11,
  abstained: true,
  audit_id: 'demo-abstain-0000',
  // The backend does attach a compliance report even when retrieval
  // abstains — abstention says the corpus could not answer the question,
  // not that no obligation applies. But a question carrying no
  // formulation facts screens to nothing, so `null` is what this case
  // actually returns; showing blocking duties beside an abstention
  // would be incoherent.
  compliance: null,
};

export const DEMO_CASES = [
  {
    id: 'c-8f21',
    status: 'drafted',
    created_at: '2026-08-28T09:12:00+00:00',
    updated_at: '2026-09-02T16:40:00+00:00',
    intake: {
      applicant_name: 'Vaidya Meera Kulkarni',
      invention_title: 'Process for a standardised Ashwagandha–Guduchi extract with enhanced bioavailability',
      inventors: ['Meera Kulkarni', 'R. Subramanian'],
      formulation_type: 'proprietary',
      jurisdiction: 'india',
      applicant_category: 'indian_individual',
      resource_origin: 'india',
      resource_cultivation: 'cultivated',
      priority_date: '2025-11-14',
      filing_date: null, fer_issued_date: null, grant_date: null,
    },
  },
  {
    id: 'c-3a07',
    status: 'prechecked',
    created_at: '2026-09-01T11:02:00+00:00',
    updated_at: '2026-09-03T08:20:00+00:00',
    intake: {
      applicant_name: 'Himavan Botanicals Pvt. Ltd.',
      invention_title: 'Topical formulation for inflammatory joint conditions',
      inventors: ['A. Nair'],
      formulation_type: 'phytopharmaceutical',
      jurisdiction: 'india',
      applicant_category: 'foreign_controlled_entity',
      resource_origin: 'india',
      resource_cultivation: 'wild_collected',
      priority_date: '2026-02-02',
      filing_date: null, fer_issued_date: null, grant_date: null,
    },
  },
  {
    id: 'c-11b5',
    status: 'handed_off',
    created_at: '2026-07-04T10:00:00+00:00',
    updated_at: '2026-08-19T14:55:00+00:00',
    intake: {
      applicant_name: 'Kerala Ayurveda Collective',
      invention_title: 'Regional preparation of a traditional decoction — GI route assessment',
      inventors: ['Collective (association of producers)'],
      formulation_type: 'classical',
      jurisdiction: 'india',
      applicant_category: 'indian_entity',
      resource_origin: 'india',
      resource_cultivation: 'cultivated',
      priority_date: '2024-06-01',
      filing_date: '2024-09-15', fer_issued_date: null, grant_date: null,
    },
  },
];

export const DEMO_DEADLINES = [
  { rule_id: 'convention_priority', label: 'File a convention application claiming this priority', anchor_field: 'priority_date', anchor_date: '2025-11-14', due_date: '2026-11-14', days_remaining: 71, status: 'upcoming', review_status: 'verified', legal_basis: { act_name: 'Paris Convention for the Protection of Industrial Property', section: 'Article 4C(1)' }, note: 'The 12-month Paris Convention priority period.' },
  { rule_id: 'pct_national_phase', label: 'Enter national phase in India from a PCT application', anchor_field: 'priority_date', anchor_date: '2025-11-14', due_date: '2028-06-14', days_remaining: 1014, status: 'upcoming', review_status: 'verified', legal_basis: { act_name: 'Patent Cooperation Treaty', section: 'Article 22' }, note: 'Applies to the PCT route only.' },
  { rule_id: 'request_for_examination', label: 'File a request for examination (Form 18)', anchor_field: 'priority_date', anchor_date: '2025-11-14', due_date: '2028-06-14', days_remaining: 1014, status: 'upcoming', review_status: 'draft', legal_basis: { act_name: 'The Patents Rules, 2003', section: 'Rule 24B (as amended)' }, note: 'Historically 48 months; the 2024 amendment is understood to have reduced this. Confirm before relying on it.' },
  { rule_id: 'fer_response', label: 'Respond to the First Examination Report', anchor_field: 'fer_issued_date', anchor_date: null, due_date: null, days_remaining: null, status: 'anchor_unknown', review_status: 'draft', legal_basis: { act_name: 'The Patents Rules, 2003', section: 'Rule 24B(6)' }, note: 'Starts when the FER is issued.' },
  { rule_id: 'form_27_working_statement', label: 'File the statement of working (Form 27)', anchor_field: 'grant_date', anchor_date: null, due_date: null, days_remaining: null, status: 'anchor_unknown', review_status: 'draft', legal_basis: { act_name: 'The Patents Rules, 2003', section: 'Rule 131' }, note: 'Only applies once granted.' },
];

export const DEMO_REVIEW_QUEUE = [
  { id: 'q-1', source_name: 'biological-diversity-amendment-act-2023', url: 'https://egazette.gov.in/…/247815.pdf', act_name: 'The Biological Diversity (Amendment) Act, 2023', jurisdiction: 'india', tier: 'mandatory_review', reason: 'source is priority=critical — always reviewed', status: 'pending', needs_audit: false, created_at: '2026-09-03T06:00:00+00:00', decided_at: null, decided_by: null, notes: null, ingest_result: null },
  { id: 'q-2', source_name: 'patents-act-1970', url: 'https://www.indiacode.nic.in/handle/123456789/1979', act_name: 'The Patents Act, 1970', jurisdiction: 'india', tier: 'publish_then_audit', reason: 'official source, 7.40% byte change exceeds auto-publish threshold', status: 'published', needs_audit: true, created_at: '2026-09-02T06:00:00+00:00', decided_at: null, decided_by: null, notes: null, ingest_result: '{"ok": true, "chunks": 142}' },
  { id: 'q-3', source_name: 'wipo-gratk-2024', url: 'https://www.wipo.int/treaties/en/ip/gratk/', act_name: 'WIPO Treaty on Intellectual Property, Genetic Resources and Associated Traditional Knowledge, 2024', jurisdiction: 'international', tier: 'auto_publish', reason: 'official source, 0.30% byte change ≤ 2% threshold', status: 'published', needs_audit: false, created_at: '2026-09-01T06:00:00+00:00', decided_at: '2026-09-01T06:00:12+00:00', decided_by: 'scheduler', notes: null, ingest_result: '{"ok": true, "chunks": 38}' },
];
