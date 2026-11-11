-- Run once: Supabase dashboard -> SQL Editor -> New query -> paste -> Run

create table if not exists docs (
  collection text not null,
  id         text not null,
  data       jsonb not null default '{}'::jsonb,
  updated_at timestamptz not null default now(),
  primary key (collection, id)
);

create table if not exists allowed_emails (email text primary key);

alter table docs enable row level security;
alter table allowed_emails enable row level security;   -- no policies = nobody can read the list through the app

create or replace function is_member() returns boolean
language sql security definer set search_path = public stable as $$
  select exists (select 1 from allowed_emails where email = lower(auth.jwt() ->> 'email'))
$$;

drop policy if exists docs_read on docs;
drop policy if exists docs_insert on docs;
drop policy if exists docs_update on docs;
drop policy if exists docs_delete on docs;
create policy docs_read   on docs for select to authenticated using (is_member());
create policy docs_insert on docs for insert to authenticated
  with check (is_member());
create policy docs_update on docs for update to authenticated
  using (is_member()) with check (is_member());
create policy docs_delete on docs for delete to authenticated using (is_member());

-- live updates between coders
do $$ begin
  alter publication supabase_realtime add table docs;
exception when duplicate_object then null;
end $$;

-- The one shared group account (create it in Authentication -> Users, see SETUP.md). Must match groupEmail in supabase-config.js.
insert into allowed_emails (email) values ('group@hudstudy.com') on conflict do nothing;
