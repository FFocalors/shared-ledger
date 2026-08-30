create type public.expense_split_method as enum ('aa', 'manual');

create table public.expenses (
  id uuid primary key default extensions.gen_random_uuid(),
  ledger_unit_id uuid not null references public.ledger_units(id) on delete restrict,
  title text not null check (length(btrim(title)) > 0),
  original_amount numeric(20,4) not null check (original_amount <> 0),
  original_currency character(3) not null check (original_currency ~ '^[A-Z]{3}$'),
  fx_rate numeric(20,10) not null check (fx_rate > 0),
  base_amount numeric(20,1) not null
    check (base_amount = pg_catalog.round(original_amount * fx_rate, 1)),
  split_method public.expense_split_method not null,
  occurred_at timestamptz not null default now(),
  note text,
  original_expense_id uuid references public.expenses(id) on delete restrict,
  created_by uuid not null references auth.users(id) on delete restrict,
  updated_by uuid not null references auth.users(id) on delete restrict,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  version bigint not null default 1 check (version >= 1),
  is_deleted boolean not null default false,
  deleted_at timestamptz,
  deleted_by uuid references auth.users(id) on delete set null,
  constraint expenses_not_self_reference
    check (original_expense_id is null or original_expense_id <> id),
  constraint expenses_lifecycle_consistency
    check ((is_deleted and deleted_at is not null) or (not is_deleted and deleted_at is null))
);

create table public.payments (
  id uuid primary key default extensions.gen_random_uuid(),
  expense_id uuid not null references public.expenses(id) on delete restrict,
  participant_id uuid not null references public.participants(id) on delete restrict,
  amount numeric(20,4) not null check (amount <> 0),
  created_at timestamptz not null default now(),
  unique (expense_id, participant_id)
);

create table public.splits (
  id uuid primary key default extensions.gen_random_uuid(),
  expense_id uuid not null references public.expenses(id) on delete restrict,
  participant_id uuid not null references public.participants(id) on delete restrict,
  amount numeric(20,4) not null check (amount <> 0),
  created_at timestamptz not null default now(),
  unique (expense_id, participant_id)
);

create index expenses_ledger_unit_active_occurred_idx
  on public.expenses (ledger_unit_id, is_deleted, occurred_at desc, id);
create index expenses_original_expense_id_idx
  on public.expenses (original_expense_id);
create index expenses_created_by_idx on public.expenses (created_by);
create index expenses_updated_by_idx on public.expenses (updated_by);
create index expenses_deleted_by_idx on public.expenses (deleted_by);
create index payments_participant_id_idx on public.payments (participant_id);
create index splits_participant_id_idx on public.splits (participant_id);

create trigger expenses_updated_at
before update on public.expenses
for each row execute function public.set_updated_at();

alter table public.expenses enable row level security;
alter table public.payments enable row level security;
alter table public.splits enable row level security;

revoke all on table public.expenses, public.payments, public.splits
  from public, anon, authenticated;
