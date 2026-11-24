-- Debrief Desk CRM schema (SQLite). All people, firms and figures are fictional.
-- Dates are ISO 'YYYY-MM-DD'; applications.next_interview_at may be 'YYYY-MM-DD HH:MM'.

CREATE TABLE consultants (
  id INTEGER PRIMARY KEY,
  name TEXT NOT NULL,
  desk TEXT NOT NULL                -- 'Quant Research' | 'Low-Latency Engineering' | 'AI/ML'
);

CREATE TABLE clients (
  id INTEGER PRIMARY KEY,
  name TEXT NOT NULL,
  kind TEXT NOT NULL,               -- 'Hedge fund' | 'Prop trading firm' | 'AI lab'
  city TEXT NOT NULL
);

CREATE TABLE roles (
  id INTEGER PRIMARY KEY,
  client_id INT NOT NULL REFERENCES clients(id),
  title TEXT NOT NULL,
  team TEXT,
  comp_band TEXT,                   -- e.g. '£120k-£190k base + discretionary bonus'
  status TEXT NOT NULL              -- 'open' | 'filled' | 'on hold'
);

CREATE TABLE candidates (
  id INTEGER PRIMARY KEY,
  name TEXT NOT NULL,
  current_employer TEXT,
  current_title TEXT,
  location TEXT,
  skills TEXT,                      -- comma-separated
  base_salary INT,                  -- annual base, in currency below
  currency TEXT,                    -- 'GBP' | 'EUR' | 'USD'
  notice_weeks INT,
  non_compete_months INT,           -- 0 = none
  consultant_id INT REFERENCES consultants(id),   -- the consultant who owns the candidate
  email TEXT,
  phone TEXT,
  known_as TEXT,                    -- the name to greet them by, e.g. 'Mei Lin'
  pronouns TEXT                     -- 'he' | 'she' | 'they'
);

CREATE TABLE applications (
  id INTEGER PRIMARY KEY,
  candidate_id INT NOT NULL REFERENCES candidates(id),
  role_id INT NOT NULL REFERENCES roles(id),
  stage TEXT NOT NULL,              -- 'sourced','screened','submitted','first_round','second_round','final_round','offer','placed','rejected','withdrawn'
  stage_updated TEXT,               -- date the stage last changed
  next_interview_at TEXT,           -- 'YYYY-MM-DD HH:MM' or NULL
  offer_sent_at TEXT,               -- date or NULL
  status TEXT NOT NULL              -- 'active' | 'closed'
);

CREATE TABLE activities (
  id INTEGER PRIMARY KEY,
  candidate_id INT NOT NULL REFERENCES candidates(id),
  consultant_id INT REFERENCES consultants(id),
  kind TEXT NOT NULL,               -- 'call' | 'email' | 'note'
  at TEXT NOT NULL,                 -- date 'YYYY-MM-DD'
  with_party TEXT NOT NULL,         -- 'candidate' (contact with the candidate) | 'client' (with the hiring firm) | 'internal' (a note)
  summary TEXT
);

CREATE TABLE debriefs (
  id INTEGER PRIMARY KEY,
  application_id INT REFERENCES applications(id),
  candidate_id INT REFERENCES candidates(id),
  client_id INT REFERENCES clients(id),
  round TEXT,                       -- e.g. 'first round', 'final round'
  held_on TEXT,                     -- date of the debrief call
  title TEXT,                       -- first header line of the transcript
  transcript TEXT
);

CREATE INDEX idx_applications_candidate ON applications(candidate_id);
CREATE INDEX idx_applications_role ON applications(role_id);
CREATE INDEX idx_activities_candidate ON activities(candidate_id, at);
CREATE INDEX idx_debriefs_client ON debriefs(client_id, held_on);
