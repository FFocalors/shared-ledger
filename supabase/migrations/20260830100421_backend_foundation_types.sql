create type public.activity_type as enum ('normal', 'large');
create type public.ledger_unit_type as enum ('default', 'root', 'sub_activity');
create schema if not exists private;
