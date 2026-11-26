-- SignalCore schema v2 (SQLite; DuckDB can ATTACH the file directly).
-- Fictional company: "Keystone Directory", an identity, device and AI-agent access platform.
-- Pillars: SAY (qualitative_feedback), DO (telemetry_events), PAY (accounts, crm_opportunities).
-- gt_* columns are ground truth planted by the generator: hidden from agents, read only by evals.

------------------------------------------------------------------ reference
CREATE TABLE modules (
  module_id TEXT PRIMARY KEY, name TEXT NOT NULL,
  lifecycle_stage TEXT NOT NULL                 -- discovery | pilot | growth | mature
);
CREATE TABLE features (
  feature_key TEXT PRIMARY KEY, module_id TEXT NOT NULL REFERENCES modules(module_id), name TEXT NOT NULL
);
CREATE TABLE feature_estimates (                -- engineering's rough sizing, editable by PMs
  feature_key TEXT PRIMARY KEY REFERENCES features(feature_key),
  effort_weeks REAL NOT NULL,                   -- team-weeks to ship a fix for the main problem in this area
  estimate_confidence TEXT NOT NULL             -- low | medium | high
);
CREATE TABLE capability_investments (
  module_id TEXT NOT NULL REFERENCES modules(module_id), quarter TEXT NOT NULL, eng_fte REAL NOT NULL,
  PRIMARY KEY (module_id, quarter)
);
CREATE TABLE roadmap_items (                    -- the Global Prioritization List as PMs keep it today
  item_id TEXT PRIMARY KEY, title TEXT NOT NULL, description TEXT NOT NULL,
  status TEXT NOT NULL,                         -- proposed | committed | in_build
  target_quarter TEXT, cited_sources TEXT,      -- e.g. 'gong,pendo,sfdc'
  gt_theme_id TEXT
);

------------------------------------------------------------------ PAY
CREATE TABLE accounts (
  account_id TEXT PRIMARY KEY, name TEXT NOT NULL, domain TEXT,
  segment TEXT NOT NULL, industry TEXT NOT NULL, region TEXT NOT NULL,
  is_customer INTEGER NOT NULL, is_icp INTEGER NOT NULL, seats INTEGER NOT NULL,
  arr_usd INTEGER NOT NULL, renewal_date DATE, csm_health TEXT
);
CREATE TABLE contacts (
  contact_id TEXT PRIMARY KEY, account_id TEXT NOT NULL REFERENCES accounts(account_id),
  name TEXT NOT NULL, email TEXT NOT NULL, persona TEXT NOT NULL
);
CREATE TABLE crm_opportunities (
  opp_id TEXT PRIMARY KEY, account_id TEXT NOT NULL REFERENCES accounts(account_id),
  opp_type TEXT NOT NULL, stage TEXT NOT NULL, status TEXT NOT NULL,   -- new_logo|expansion|renewal ; open|won|lost
  amount_usd INTEGER NOT NULL, close_date DATE NOT NULL,
  loss_reason TEXT, notes TEXT, gt_theme_id TEXT
);

------------------------------------------------------------------ SAY (raw, as exported)
CREATE TABLE qualitative_feedback (
  feedback_id TEXT PRIMARY KEY, source TEXT NOT NULL, source_ref TEXT NOT NULL,
  reporter_email TEXT, reporter_company TEXT,   -- messy: personal emails, typos, aliases
  created_at TIMESTAMP NOT NULL, body TEXT NOT NULL,
  account_id TEXT, match_method TEXT, match_confidence REAL,   -- filled by the identity resolver
  gt_account_id TEXT, gt_theme_id TEXT, gt_second_theme_id TEXT
);

------------------------------------------------------------------ DO
CREATE TABLE telemetry_events (
  event_id TEXT PRIMARY KEY, ts TIMESTAMP NOT NULL,
  account_id TEXT NOT NULL REFERENCES accounts(account_id), user_hash TEXT NOT NULL,
  feature_key TEXT NOT NULL REFERENCES features(feature_key),
  event_name TEXT NOT NULL,                     -- task_started | task_completed | task_abandoned
  duration_ms INTEGER
);
CREATE INDEX ix_tel_feat ON telemetry_events(feature_key, account_id);

------------------------------------------------------------------ written by the pipeline
CREATE TABLE agent_runs (
  run_id TEXT PRIMARY KEY, started_at TIMESTAMP, finished_at TIMESTAMP, mode TEXT,   -- live | replay | stub
  status TEXT, tokens_in INTEGER DEFAULT 0, tokens_out INTEGER DEFAULT 0, cost_usd REAL DEFAULT 0
);
CREATE TABLE agent_steps (
  run_id TEXT, step_no INTEGER, node TEXT, label TEXT, started_at TIMESTAMP, ms INTEGER,
  model TEXT, tokens_in INTEGER, tokens_out INTEGER, cost_usd REAL, detail TEXT,     -- detail: JSON (SQL, rows, notes)
  PRIMARY KEY (run_id, step_no)
);
CREATE TABLE feedback_enrichment (
  run_id TEXT, feedback_id TEXT, cluster_id INTEGER, theme_id TEXT,
  is_product_feedback INTEGER, urgency INTEGER, sentiment REAL, mentions_workaround INTEGER, persona TEXT,
  PRIMARY KEY (run_id, feedback_id)
);
CREATE TABLE themes (
  run_id TEXT, theme_id TEXT, title TEXT NOT NULL, problem_statement TEXT NOT NULL,
  module_id TEXT, feature_key TEXT, keywords TEXT, size INTEGER,
  PRIMARY KEY (run_id, theme_id)
);
CREATE TABLE theme_scores (
  run_id TEXT, theme_id TEXT,
  q_score REAL, b_score REAL, c_score REAL, rule_penalty REAL, skeptic_penalty REAL,
  evidence_score INTEGER, archetype TEXT,
  cod_week_usd REAL, cod_adj_week_usd REAL, effort_weeks REAL, cd3 REAL, urgency_profile TEXT, priority_rank INTEGER,
  metrics TEXT,                                 -- JSON: pillar metrics + CoD components
  rule_notes TEXT, skeptic_notes TEXT, skeptic_citations TEXT,
  PRIMARY KEY (run_id, theme_id)
);
CREATE TABLE gpl_links (run_id TEXT, item_id TEXT, theme_id TEXT, similarity REAL, PRIMARY KEY (run_id, item_id));
CREATE TABLE brief_claims (
  run_id TEXT, claim_id TEXT, section TEXT, text TEXT, attempt INTEGER,
  status TEXT,                                  -- grounded | failed | dropped
  judge_reason TEXT, PRIMARY KEY (run_id, claim_id)
);
CREATE TABLE evidence_citations (
  run_id TEXT, claim_id TEXT, fact_id TEXT, PRIMARY KEY (run_id, claim_id, fact_id)
);
CREATE TABLE facts (                            -- the only numbers the briefing agent may use
  run_id TEXT, fact_id TEXT, theme_id TEXT, label TEXT, value TEXT, source_sql TEXT,
  PRIMARY KEY (run_id, fact_id)
);
CREATE TABLE evals (run_id TEXT, metric TEXT, value REAL, detail TEXT, PRIMARY KEY (run_id, metric));
CREATE TABLE pm_overrides (
  override_id INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT, theme_id TEXT,
  field TEXT, old_value TEXT, new_value TEXT, reason TEXT NOT NULL, author TEXT, created_at TIMESTAMP
);
CREATE TABLE ask_log (
  ask_id INTEGER PRIMARY KEY AUTOINCREMENT, asked_at TIMESTAMP, question TEXT, answer TEXT, sql TEXT, rows TEXT,
  cost_usd REAL
);
