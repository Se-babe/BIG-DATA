-- Global Patent Intelligence — SQLite schema (PatentsView-style inputs)
PRAGMA foreign_keys = OFF;

DROP TABLE IF EXISTS relationships;
DROP TABLE IF EXISTS patents;
DROP TABLE IF EXISTS inventors;
DROP TABLE IF EXISTS companies;

CREATE TABLE patents (
  patent_id    TEXT PRIMARY KEY,
  title        TEXT,
  abstract     TEXT,
  filing_date  TEXT,
  year         INTEGER,
  cpc_primary  TEXT
);

CREATE TABLE inventors (
  inventor_id  TEXT PRIMARY KEY,
  name         TEXT,
  country      TEXT
);

CREATE TABLE companies (
  company_id   TEXT PRIMARY KEY,
  name         TEXT
);

-- One row per (patent, inventor); company_id is the primary assignee for that patent when known
CREATE TABLE relationships (
  patent_id    TEXT NOT NULL,
  inventor_id  TEXT NOT NULL,
  company_id   TEXT,
  PRIMARY KEY (patent_id, inventor_id)
);

CREATE INDEX idx_rel_patent ON relationships (patent_id);
CREATE INDEX idx_rel_inventor ON relationships (inventor_id);
CREATE INDEX idx_rel_company ON relationships (company_id);
CREATE INDEX idx_patents_year ON patents (year);
