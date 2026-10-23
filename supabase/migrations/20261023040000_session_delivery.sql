-- T3.1 prerequisite (AuDHS ADR 0021 draft): how the tutor teaches in this session, chosen by the learner.
-- socratic = guiding questions (the standalone default); explicit = direct explanation, then one check question
-- (the AuDHS default). Owner-only RLS on tutor.session already covers the new column.
alter table tutor.session add column if not exists delivery text not null default 'socratic'
  check (delivery in ('socratic', 'explicit'));
