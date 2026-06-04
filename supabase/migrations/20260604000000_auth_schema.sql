-- Phase A — Auth foundation: profiles + team_memberships + team_recipients with RLS.
--
-- profiles: 1:1 with auth.users; carries role.
-- team_memberships: which teams a user can access.
-- team_recipients: per-team email recipients for the Game Briefings email
--                  (replaces the Modal Dict pitching_recap_settings_store).
--
-- Seeds aroncm@gmail.com as the initial admin if that auth user already exists.

create table if not exists profiles (
  user_id uuid primary key references auth.users(id) on delete cascade,
  role text not null check (role in ('admin', 'viewer')),
  full_name text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists team_memberships (
  user_id uuid not null references auth.users(id) on delete cascade,
  team_abbr text not null,
  granted_by uuid references auth.users(id),
  granted_at timestamptz not null default now(),
  primary key (user_id, team_abbr)
);

create table if not exists team_recipients (
  id uuid primary key default gen_random_uuid(),
  team_abbr text not null,
  email text not null,
  name text,
  briefings_enabled boolean not null default true,
  created_by uuid references auth.users(id),
  created_at timestamptz not null default now()
);

create unique index if not exists team_recipients_team_email_unique
  on team_recipients (team_abbr, lower(email));

create or replace function is_admin(uid uuid) returns boolean
  language sql security definer set search_path = public
  as $$
    select exists (select 1 from profiles where user_id = uid and role = 'admin');
  $$;

alter table profiles enable row level security;
alter table team_memberships enable row level security;
alter table team_recipients enable row level security;

drop policy if exists profiles_self_read on profiles;
drop policy if exists profiles_admin_all on profiles;
create policy profiles_self_read on profiles for select using (auth.uid() = user_id);
create policy profiles_admin_all  on profiles for all
  using (is_admin(auth.uid())) with check (is_admin(auth.uid()));

drop policy if exists tm_self_read on team_memberships;
drop policy if exists tm_admin_all on team_memberships;
create policy tm_self_read on team_memberships for select using (auth.uid() = user_id);
create policy tm_admin_all on team_memberships for all
  using (is_admin(auth.uid())) with check (is_admin(auth.uid()));

drop policy if exists tr_member_read on team_recipients;
drop policy if exists tr_admin_write on team_recipients;
create policy tr_member_read on team_recipients for select using (
  is_admin(auth.uid())
  or exists (
    select 1 from team_memberships
    where user_id = auth.uid() and team_abbr = team_recipients.team_abbr
  )
);
create policy tr_admin_write on team_recipients for all
  using (is_admin(auth.uid())) with check (is_admin(auth.uid()));

-- Seed: aroncm@gmail.com is the initial admin (assumes the auth user already
-- exists from the-brain's existing Supabase auth).
insert into profiles (user_id, role, full_name)
  select id, 'admin', 'Craig Aron'
    from auth.users
    where lower(email) = 'aroncm@gmail.com'
  on conflict (user_id) do nothing;
