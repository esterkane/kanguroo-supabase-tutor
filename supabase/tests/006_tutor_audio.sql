begin;
select plan(4);

select is((select public from storage.buckets where id = 'tutor-audio'), false, 'tutor-audio bucket is private');
select is((select allowed_mime_types from storage.buckets where id = 'tutor-audio'),
          array['audio/mpeg', 'audio/wav'], 'only audio may be stored');
select is((select count(*)::int from pg_policies where schemaname = 'storage' and tablename = 'objects'
             and (qual ilike '%tutor-audio%' or with_check ilike '%tutor-audio%')),
          0, 'no storage policy opens tutor-audio to learners (signed URLs only)');
set local role anon;
select is((select count(*)::int from storage.objects where bucket_id = 'tutor-audio'), 0,
          'anon sees no cached audio objects');

select * from finish();
rollback;
