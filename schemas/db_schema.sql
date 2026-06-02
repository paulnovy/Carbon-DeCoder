-- Foundation schema (MVP-0 -> MVP-1 direction)

create table if not exists references (
  id text primary key,
  version text not null,
  source text,
  contig_style text,
  status text not null,
  created_at timestamptz default now()
);

create table if not exists projects (
  id text primary key,
  name text not null,
  description text,
  created_at timestamptz default now()
);

create table if not exists samples (
  id text primary key,
  project_id text not null references projects(id),
  sample_id text not null,
  reference_id text not null references references(id),
  created_at timestamptz default now()
);

create table if not exists runs (
  id text primary key,
  project_id text not null references projects(id),
  sample_id text not null references samples(id),
  reference_id text not null references references(id),
  mode text not null,
  status text not null,
  command_line text,
  parameters jsonb default '{}'::jsonb,
  provenance jsonb default '{}'::jsonb,
  created_at timestamptz default now(),
  finished_at timestamptz
);

create table if not exists run_events (
  id bigserial primary key,
  run_id text not null references runs(id),
  event_type text not null,
  payload jsonb default '{}'::jsonb,
  created_at timestamptz default now()
);

create table if not exists run_steps (
  id text primary key,
  run_id text not null references runs(id),
  step_name text not null,
  status text not null,
  progress_pct numeric(5,2) default 0,
  runtime_sec integer default 0,
  cpu_pct numeric(6,2),
  ram_mb numeric(10,2),
  disk_mb numeric(10,2),
  current_file text,
  last_log text,
  warning text,
  error text,
  created_at timestamptz default now(),
  updated_at timestamptz default now()
);

create table if not exists run_logs (
  id bigserial primary key,
  run_id text not null references runs(id),
  line_no integer not null,
  message text not null,
  created_at timestamptz default now()
);

create table if not exists qc_metrics (
  id bigserial primary key,
  project_id text not null references projects(id),
  sample_id text not null references samples(id),
  run_id text not null references runs(id),
  reference_id text not null references references(id),
  total_reads bigint,
  gc_content_pct numeric(6,3),
  duplication_rate_pct numeric(6,3),
  mean_read_length numeric(10,3),
  status text not null,
  source_files jsonb default '[]'::jsonb,
  created_at timestamptz default now()
);

create table if not exists trust_scores (
  id bigserial primary key,
  project_id text not null references projects(id),
  sample_id text not null references samples(id),
  run_id text not null references runs(id),
  reference_id text not null references references(id),
  contig text,
  start_pos bigint,
  end_pos bigint,
  trust_score numeric(5,2),
  trust_label text,
  factors jsonb default '{}'::jsonb,
  created_at timestamptz default now()
);

create table if not exists giab_benchmarks (
  id text primary key,
  project_id text not null references projects(id),
  sample_id text not null references samples(id),
  run_id text not null references runs(id),
  reference_id text not null references references(id),
  precision numeric(8,6),
  recall numeric(8,6),
  f1 numeric(8,6),
  stratified_metrics jsonb default '{}'::jsonb,
  regression_alert text,
  created_at timestamptz default now()
);

create table if not exists reports (
  id text primary key,
  project_id text not null references projects(id),
  sample_id text not null references samples(id),
  run_id text not null references runs(id),
  reference_id text not null references references(id),
  report_type text not null,
  status text not null,
  html_path text,
  json_path text,
  parquet_path text,
  created_at timestamptz default now()
);
