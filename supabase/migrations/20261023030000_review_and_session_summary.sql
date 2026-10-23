-- T2.5: FSRS card per ledger topic (backend/tutor/review.py writes it together with next_review) and the
-- session-end summary (TutorTurn.session_end: understand, proved, still_wrong, retrieval_questions, next_case).
-- Both live on owner-only tables, so the existing RLS and grants cover them.
alter table tutor.mastery_ledger add column if not exists fsrs_card jsonb;
alter table tutor.session add column if not exists summary jsonb;
create index if not exists mastery_ledger_due_idx on tutor.mastery_ledger (user_id, next_review);
comment on column tutor.mastery_ledger.fsrs_card is 'py-fsrs Card.to_dict(); next_review = card due';
comment on column tutor.session.summary is 'SessionEnd block of the turn that ended the session';
