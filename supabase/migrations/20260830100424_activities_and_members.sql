create table public.activities (
 id uuid primary key default gen_random_uuid(), join_code text not null unique check (join_code ~ '^[0-9]{8}$'),
 name text not null check (length(btrim(name)) > 0), type public.activity_type not null,
 base_currency char(3) not null default 'CNY' check (base_currency ~ '^[A-Z]{3}$'),
 multi_currency_enabled boolean not null default false, created_by uuid not null references auth.users(id) on delete restrict,
 created_at timestamptz not null default now(), updated_at timestamptz not null default now(), archived_at timestamptz,
 is_deleted boolean not null default false, deleted_at timestamptz, deleted_by uuid references auth.users(id) on delete set null
);
create table public.activity_members (
 id uuid primary key default gen_random_uuid(), activity_id uuid not null references public.activities(id) on delete restrict,
 user_id uuid not null references auth.users(id) on delete restrict, joined_at timestamptz not null default now(), created_at timestamptz not null default now(), unique(activity_id,user_id)
);
create index activities_created_by_idx on public.activities(created_by);
create index activity_members_activity_id_idx on public.activity_members(activity_id);
create index activity_members_user_id_idx on public.activity_members(user_id);
