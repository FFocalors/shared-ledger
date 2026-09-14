begin;

-- Repair the two jobs created by 20260913120850.  The deployed pg_net API is
-- exposed through the `net` schema; Vault values remain outside migration
-- history.
select cron.unschedule('shared_ledger_ecb_reference_1630_utc_weekdays');
select cron.unschedule('shared_ledger_ecb_reference_1830_utc_weekdays');

select cron.schedule(
  'shared_ledger_ecb_reference_1630_utc_weekdays',
  '30 16 * * 1-5',
  $$
    select net.http_post(
      url := (select decrypted_secret from vault.decrypted_secrets where name = 'project_url')
             || '/functions/v1/sync-exchange-rates',
      headers := jsonb_build_object(
        'Content-Type', 'application/json',
        'apikey', (select decrypted_secret from vault.decrypted_secrets where name = 'publishable_key')
      ),
      body := '{}'::jsonb,
      timeout_milliseconds := 10000
    ) as request_id;
  $$
);

select cron.schedule(
  'shared_ledger_ecb_reference_1830_utc_weekdays',
  '30 18 * * 1-5',
  $$
    select net.http_post(
      url := (select decrypted_secret from vault.decrypted_secrets where name = 'project_url')
             || '/functions/v1/sync-exchange-rates',
      headers := jsonb_build_object(
        'Content-Type', 'application/json',
        'apikey', (select decrypted_secret from vault.decrypted_secrets where name = 'publishable_key')
      ),
      body := '{}'::jsonb,
      timeout_milliseconds := 10000
    ) as request_id;
  $$
);

commit;
