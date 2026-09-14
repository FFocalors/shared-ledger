begin;

-- Supabase-hosted Cron/Net setup.  The extension schemas are explicit so the
-- application public schema remains clean; Vault values are populated outside
-- migrations and are never embedded in this file.
create extension if not exists pg_cron with schema pg_catalog;
create extension if not exists pg_net with schema extensions;

grant usage on schema cron to postgres;
grant all privileges on all tables in schema cron to postgres;

-- Job names are stable and case-sensitive. cron.schedule replaces an existing
-- job with the same name, making this migration safe to apply once per env.
select cron.schedule(
  'shared_ledger_ecb_reference_1630_utc_weekdays',
  '30 16 * * 1-5',
  $$
    select extensions.http_post(
      url := (select decrypted_secret from vault.decrypted_secrets where name = 'project_url')
             || '/functions/v1/sync-exchange-rates',
      headers := jsonb_build_object(
        'Content-Type', 'application/json',
        'apikey', (select decrypted_secret from vault.decrypted_secrets where name = 'publishable_key')
      ),
      body := '{}'::jsonb
    ) as request_id;
  $$
);

select cron.schedule(
  'shared_ledger_ecb_reference_1830_utc_weekdays',
  '30 18 * * 1-5',
  $$
    select extensions.http_post(
      url := (select decrypted_secret from vault.decrypted_secrets where name = 'project_url')
             || '/functions/v1/sync-exchange-rates',
      headers := jsonb_build_object(
        'Content-Type', 'application/json',
        'apikey', (select decrypted_secret from vault.decrypted_secrets where name = 'publishable_key')
      ),
      body := '{}'::jsonb
    ) as request_id;
  $$
);

commit;
