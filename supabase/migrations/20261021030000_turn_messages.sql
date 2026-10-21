-- tutor.turn stores the conversation verbatim. Current Claude models only replay earlier thinking blocks
-- while every earlier message is byte-identical, so the router persists each API message exactly as the
-- orchestrator returned it (`message`) and replays them in insertion order (`seq`; all messages of one turn
-- share the same now()). Per-turn context goes in as mid-conversation system messages, hence role 'system'.

alter table tutor.turn add column if not exists message jsonb;
alter table tutor.turn add column if not exists seq bigint generated always as identity;

alter table tutor.turn drop constraint if exists turn_role_check;
alter table tutor.turn add constraint turn_role_check check (role in ('user', 'assistant', 'tool', 'system'));

create index if not exists turn_session_seq_idx on tutor.turn (session_id, seq);

comment on column tutor.turn.message is 'Anthropic API message exactly as sent/received (append-only history)';
comment on column tutor.turn.content is 'Display text: learner text, assistant Markdown, or a short summary for tool/system rows';
