-- T2.2 incident mode: the app-owned incident model of a session, merged turn by turn
-- (backend/tutor/incident.py). Same owner-only RLS and grants as the rest of tutor.session.
alter table tutor.session add column if not exists incident jsonb;
comment on column tutor.session.incident is
  'IncidentState: {model: Incident, sources: {field: tutor|learner}, conflicts: [...]}; null until the first incident turn';
