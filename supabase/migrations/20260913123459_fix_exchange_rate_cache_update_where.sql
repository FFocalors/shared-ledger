-- API-role safe-update requires every UPDATE to carry an explicit predicate.
create or replace function public.replace_exchange_rate_cache(
  p_ecb_date date,
  p_rates jsonb
)
returns table(currency_count integer, pair_count integer, observed_at timestamptz)
language plpgsql
volatile
security invoker
set search_path = ''
as $function$
declare
  v_now timestamptz := pg_catalog.now();
  v_observed_at timestamptz;
  v_count integer;
  v_pairs integer := 0;
  v_item record;
  v_quote record;
  v_rate numeric(20,10);
  v_quote_rate numeric(20,10);
begin
  if current_user <> 'service_role' then
    raise exception using errcode = '42501', message = 'server sync access required';
  end if;
  if p_ecb_date is null or p_ecb_date > (v_now at time zone 'UTC')::date then
    raise exception using errcode = '22023', message = 'ECB date is invalid';
  end if;
  if p_rates is null or pg_catalog.jsonb_typeof(p_rates) <> 'object' then
    raise exception using errcode = '22023', message = 'ECB payload must be an object';
  end if;
  if p_rates ->> 'EUR' is null or (p_rates ->> 'EUR')::numeric <> 1 then
    raise exception using errcode = '22023', message = 'ECB payload must contain EUR=1';
  end if;

  select count(*) into v_count from pg_catalog.jsonb_each_text(p_rates);
  if v_count < 5 or v_count > 100 then
    raise exception using errcode = '22023', message = 'ECB payload is incomplete';
  end if;
  for v_item in select key, value from pg_catalog.jsonb_each_text(p_rates)
  loop
    if v_item.key !~ '^[A-Z]{3}$' then
      raise exception using errcode = '22023', message = 'ECB currency code is invalid';
    end if;
    v_rate := v_item.value::numeric(20,10);
    if v_rate <= 0 then
      raise exception using errcode = '22023', message = 'ECB rate must be positive';
    end if;
  end loop;

  v_observed_at := (p_ecb_date::timestamp at time zone 'UTC');
  update public.exchange_rate_supported_currencies
  set enabled = false, updated_at = v_now
  where true;
  for v_item in select key, value from pg_catalog.jsonb_each_text(p_rates)
  loop
    v_rate := v_item.value::numeric(20,10);
    insert into public.exchange_rate_supported_currencies
      (currency_code, display_name, observed_at, updated_at, enabled)
    values (v_item.key, '', v_observed_at, v_now, true)
    on conflict (currency_code) do update
      set observed_at = excluded.observed_at,
          updated_at = excluded.updated_at,
          enabled = true;

    for v_quote in select key, value from pg_catalog.jsonb_each_text(p_rates)
    loop
      if v_item.key <> v_quote.key then
        v_quote_rate := v_quote.value::numeric(20,10);
        insert into public.exchange_rate_cache
          (base_currency, quote_currency, rate, observed_at, source, updated_at)
        values (
          v_item.key,
          v_quote.key,
          pg_catalog.round(v_rate / v_quote_rate, 10),
          v_observed_at,
          'ECB_REFERENCE',
          v_now
        )
        on conflict (base_currency, quote_currency) do update
          set rate = excluded.rate,
              observed_at = excluded.observed_at,
              source = excluded.source,
              updated_at = excluded.updated_at;
        v_pairs := v_pairs + 1;
      end if;
    end loop;
  end loop;

  update public.exchange_rate_sync_state as s
  set last_succeeded_at = v_now,
      last_ecb_observed_at = v_observed_at,
      last_error_code = null,
      updated_at = v_now
  where s.singleton;
  return query select v_count, v_pairs, v_observed_at;
end;
$function$;
