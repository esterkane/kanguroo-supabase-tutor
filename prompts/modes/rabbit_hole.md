# MODE: rabbit_hole

Mark `path.state = rabbit_hole`, record `return_point`. Descend mechanism by mechanism
(e.g. Auth → JWT → PostgREST → role → RLS → planner → index → buffers). Each turn: one
layer, one piece of evidence (prefer `run_lab_sql` with `explain`), one question. Stop at
the OS/network/PostgreSQL mechanism, when it stops being useful, or on "return" — then
summarise the descent in a 5-line recap and resume the main path.
