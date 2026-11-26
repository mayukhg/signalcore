-- SignalCore synthetic data schema
-- Works in SQLite (used by generate.py) and DuckDB (swap TEXT->VARCHAR if you like).
-- Fictional company: "Keystone Directory", an IT identity, device and AI-agent access platform.
-- Three pillars of truth: what customers SAY (qualitative_feedback), DO (telemetry_events),
-- and PAY (accounts + crm_opportunities). Everything below `-- derived` is written by the agents.

------------------------------------------------------------------ reference
CREATE TABLE modules (
  module_id        TEXT PRIMARY KEY,          -- 'agent_access'
  name             TEXT NOT NULL,             -- 'AI Agent Access'
  lifecycle_stage  TEXT NOT NULL,             -- discovery | pilot | growth | mature | sunset
  launched_on      DATE
);

CREATE TABLE features (
  feature_key      TEXT PRIMARY KEY,          -- 'agent_policy_editor'
  module_id        TEXT NOT NULL REFERENCES modules(module_id),
  name             TEXT NOT NULL
);

CREATE TABLE capability_investments (       -- R&D capital allocation (from finance / Jira capacity)
  module_id        TEXT NOT NULL REFERENCES modules(module_id),
  quarter          TEXT NOT NULL,             -- '2026-Q4'
  eng_fte          REAL NOT NULL,
  PRIMARY KEY (module_id, quarter)
);

------------------------------------------------------------------ pillar 3: commercial (what they pay)
CREATE TABLE accounts (
  account_id       TEXT PRIMARY KEY,          -- 'ACC-0042'
  name             TEXT NOT NULL,
  segment          TEXT NOT NULL,             -- SMB | Mid-Market | Enterprise
  industry         TEXT NOT NULL,
  region           TEXT NOT NULL,
  is_customer      INTEGER NOT NULL,          -- 0 = prospect only
  is_icp           INTEGER NOT NULL,          -- ideal-customer-profile flag
  seats            INTEGER NOT NULL,
  arr_usd          INTEGER NOT NULL,          -- 0 for prospects
  renewal_date     DATE,
  csm_health       TEXT                       -- green | yellow | red (CSM's opinion, not evidence)
);

CREATE TABLE crm_opportunities (
  opp_id           TEXT PRIMARY KEY,
  account_id       TEXT NOT NULL REFERENCES accounts(account_id),
  opp_type         TEXT NOT NULL,             -- new_logo | expansion | renewal
  stage            TEXT NOT NULL,             -- discovery | eval | negotiation | closed
  status           TEXT NOT NULL,             -- open | won | lost
  amount_usd       INTEGER NOT NULL,
  close_date       DATE NOT NULL,
  loss_reason      TEXT,                      -- free text from the rep
  notes            TEXT,                      -- free text; may name a product gap
  gt_theme_id      TEXT                       -- ground truth label, hidden from agents, used by evals
);

CREATE TABLE contacts (
  contact_id       TEXT PRIMARY KEY,
  account_id       TEXT NOT NULL REFERENCES accounts(account_id),
  persona          TEXT NOT NULL              -- economic_buyer | it_admin | security_lead | end_user
);

------------------------------------------------------------------ pillar 1: qualitative (what they say)
CREATE TABLE qualitative_feedback (
  feedback_id      TEXT PRIMARY KEY,
  source           TEXT NOT NULL,             -- gong | zendesk | jira | idea_portal | cab
  source_ref       TEXT NOT NULL,             -- e.g. 'GONG-88123@14:02', 'ZD-40112'
  account_id       TEXT NOT NULL REFERENCES accounts(account_id),
  contact_id       TEXT REFERENCES contacts(contact_id),
  persona          TEXT NOT NULL,
  created_at       TIMESTAMP NOT NULL,
  body             TEXT NOT NULL,
  gt_theme_id      TEXT                       -- ground truth label, hidden from agents, used by evals
);

------------------------------------------------------------------ pillar 2: behavioral (what they do)
CREATE TABLE telemetry_events (              -- Pendo/Mixpanel-shaped event stream
  event_id         TEXT PRIMARY KEY,
  ts               TIMESTAMP NOT NULL,
  account_id       TEXT NOT NULL REFERENCES accounts(account_id),
  user_hash        TEXT NOT NULL,
  feature_key      TEXT NOT NULL REFERENCES features(feature_key),
  event_name       TEXT NOT NULL,             -- task_started | task_completed | task_abandoned
  duration_ms      INTEGER
);

------------------------------------------------------------------ derived (written by agents)
CREATE TABLE feedback_enrichment (           -- Cluster Agent, one row per feedback item
  feedback_id      TEXT PRIMARY KEY REFERENCES qualitative_feedback(feedback_id),
  theme_id         TEXT,                      -- NULL = unclustered noise
  sentiment        REAL,                      -- -1..1
  urgency          INTEGER,                   -- 1..5
  mentions_workaround INTEGER,
  embedding        BLOB
);

CREATE TABLE themes (                        -- Cluster Agent: canonical problem statements
  theme_id         TEXT PRIMARY KEY,
  title            TEXT NOT NULL,
  problem_statement TEXT NOT NULL,
  module_id        TEXT REFERENCES modules(module_id),
  feature_key      TEXT REFERENCES features(feature_key)
);

CREATE TABLE theme_scores (                  -- Triangulation + Skeptic agents, one row per run
  run_id           TEXT NOT NULL,
  theme_id         TEXT NOT NULL REFERENCES themes(theme_id),
  q_score          REAL, b_score REAL, c_score REAL,   -- pillar strengths 0..1
  penalty          REAL,                      -- multiplier from the Skeptic (<= 1)
  evidence_score   INTEGER,                   -- 0..100 confidence the theme is real and material
  archetype        TEXT,                      -- high_signal | silent_churn | commercial_mirage | vocal_minority | emerging
  skeptic_notes    TEXT,
  PRIMARY KEY (run_id, theme_id)
);

CREATE TABLE roadmap_items (                 -- the Global Prioritization List the PM org already keeps
  item_id          TEXT PRIMARY KEY,
  title            TEXT NOT NULL,
  theme_id         TEXT REFERENCES themes(theme_id),
  status           TEXT NOT NULL,             -- proposed | committed | in_build
  target_quarter   TEXT,
  cited_sources    TEXT                       -- what the PRD cites today, e.g. 'gong' or 'gong,pendo,sfdc'
);

CREATE TABLE evidence_citations (            -- every claim the briefing agent makes points here
  run_id           TEXT NOT NULL,
  claim_id         TEXT NOT NULL,
  table_name       TEXT NOT NULL,             -- qualitative_feedback | telemetry_events | crm_opportunities | accounts
  row_id           TEXT NOT NULL,
  PRIMARY KEY (run_id, claim_id, table_name, row_id)
);
