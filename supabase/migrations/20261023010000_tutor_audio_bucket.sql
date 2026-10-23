-- Server TTS cache (T2.6 / R11): private Storage bucket for synthesized `speech` audio.
-- No storage.objects policies for anon/authenticated: only the backend (secret key) writes and signs;
-- the browser plays an object through a short-lived signed URL.
insert into storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
values ('tutor-audio', 'tutor-audio', false, 2097152, array['audio/mpeg', 'audio/wav'])
on conflict (id) do update
  set public = false, file_size_limit = excluded.file_size_limit, allowed_mime_types = excluded.allowed_mime_types;
