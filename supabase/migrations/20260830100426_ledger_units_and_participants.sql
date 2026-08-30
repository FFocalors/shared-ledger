create table public.ledger_units (
 id uuid primary key default gen_random_uuid(), activity_id uuid not null references public.activities(id) on delete restrict,
 name text not null check (length(btrim(name)) > 0), type public.ledger_unit_type not null,
 created_at timestamptz not null default now(), updated_at timestamptz not null default now(), is_deleted boolean not null default false,
 deleted_at timestamptz, deleted_by uuid references auth.users(id) on delete set null
);
-- Cross-table normal/large versus unit-type rules are intentionally enforced by
-- the future activity/unit RPC; no fragile row trigger is introduced in Phase 1.
create table public.participants (
 id uuid primary key default gen_random_uuid(), activity_id uuid not null references public.activities(id) on delete restrict,
 name text not null check (length(btrim(name)) > 0), participant_order integer not null check (participant_order >= 0),
 created_at timestamptz not null default now(), updated_at timestamptz not null default now(), is_deleted boolean not null default false,
 deleted_at timestamptz, deleted_by uuid references auth.users(id) on delete set null, unique(activity_id,participant_order), unique(activity_id,id)
);
create table public.participant_claims (
 id uuid primary key default gen_random_uuid(), activity_id uuid not null references public.activities(id) on delete restrict,
 participant_id uuid not null, user_id uuid not null references auth.users(id) on delete restrict, claimed_at timestamptz not null default now(),
 unique(participant_id), unique(activity_id,user_id), foreign key(activity_id,participant_id) references public.participants(activity_id,id) on delete restrict
);
create index ledger_units_activity_id_idx on public.ledger_units(activity_id);
create index participants_activity_id_idx on public.participants(activity_id);
create index participant_claims_activity_id_idx on public.participant_claims(activity_id);
create index participant_claims_user_id_idx on public.participant_claims(user_id);
create or replace function public.set_updated_at() returns trigger language plpgsql set search_path = '' as $$ begin new.updated_at = now(); return new; end; $$;
create trigger profiles_updated_at before update on public.profiles for each row execute function public.set_updated_at();
create trigger activities_updated_at before update on public.activities for each row execute function public.set_updated_at();
create trigger ledger_units_updated_at before update on public.ledger_units for each row execute function public.set_updated_at();
create trigger participants_updated_at before update on public.participants for each row execute function public.set_updated_at();
