// Scheduled server-only synchronizer for the ECB daily reference XML.
// Secrets are read only from the Edge Function environment and are never
// included in responses, logs, or the database cache.

type SyncErrorCode =
  | "config_missing"
  | "upstream_unavailable"
  | "upstream_http_error"
  | "invalid_payload"
  | "database_unavailable"
  | `${RpcStage}_http_${number}${string}`

type RpcStage = "claim" | "replace" | "failure"

class SyncFailure extends Error {
  readonly code: SyncErrorCode

  constructor(code: SyncErrorCode) {
    super(code)
    this.code = code
  }
}

const json = (body: Record<string, unknown>, status = 200) =>
  new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  })

function parseEcbXml(xml: string): { date: string; rates: Record<string, string> } {
  if (xml.length === 0 || xml.length > 1_000_000) {
    throw new SyncFailure("invalid_payload")
  }

  const time = xml.match(/<Cube\b[^>]*\btime=(['"])(\d{4}-\d{2}-\d{2})\1[^>]*>/i)?.[2]
  if (!time || !/^\d{4}-\d{2}-\d{2}$/.test(time)) {
    throw new SyncFailure("invalid_payload")
  }
  const today = new Date().toISOString().slice(0, 10)
  if (time > today) {
    throw new SyncFailure("invalid_payload")
  }

  const rates: Record<string, string> = { EUR: "1" }
  const seen = new Set<string>(["EUR"])
  const cubePattern = /<Cube\b([^>]*)\/?>/gi
  for (const match of xml.matchAll(cubePattern)) {
    const attrs = match[1]
    const currency = attrs.match(/\bcurrency=(['"])([A-Za-z]{3})\1/i)?.[2]?.toUpperCase()
    const rate = attrs.match(/\brate=(['"])([0-9]+(?:\.[0-9]+)?)\1/i)?.[2]
    if (!currency && !rate) continue
    if (!currency || !rate || seen.has(currency)) {
      throw new SyncFailure("invalid_payload")
    }
    // Keep the decimal as text through the network boundary. PostgreSQL does
    // the authoritative numeric division and rounding.
    if (rate.length > 24 || Number(rate) <= 0 || !Number.isFinite(Number(rate))) {
      throw new SyncFailure("invalid_payload")
    }
    seen.add(currency)
    rates[currency] = rate
  }
  if (Object.keys(rates).length < 5) {
    throw new SyncFailure("invalid_payload")
  }
  return { date: time, rates }
}

async function callRpc(
  supabaseUrl: string,
  serviceRoleKey: string,
  stage: RpcStage,
  name: string,
  body: Record<string, unknown>,
): Promise<unknown> {
  let response: Response
  try {
    response = await fetch(`${supabaseUrl.replace(/\/$/, "")}/rest/v1/rpc/${name}`, {
      method: "POST",
      headers: {
        apikey: serviceRoleKey,
        "content-type": "application/json",
      },
      body: JSON.stringify(body),
    })
  } catch {
    throw new SyncFailure("database_unavailable")
  }
  if (!response.ok) {
    let sqlState: string | undefined
    try {
      const payload = await response.json() as { code?: unknown }
      if (typeof payload.code === "string" && /^[A-Za-z0-9]{1,32}$/.test(payload.code)) {
        sqlState = payload.code
      }
    } catch {
      // Keep the failure code limited to stage and HTTP status.
    }
    throw new SyncFailure(`${stage}_http_${response.status}${sqlState ? `_${sqlState}` : ""}`)
  }
  try {
    return await response.json()
  } catch {
    throw new SyncFailure("database_unavailable")
  }
}

function firstRow(value: unknown): Record<string, unknown> {
  const row = Array.isArray(value) ? value[0] : value
  if (!row || typeof row !== "object") throw new SyncFailure("database_unavailable")
  return row as Record<string, unknown>
}

Deno.serve(async (request) => {
  const supabaseUrl = Deno.env.get("SUPABASE_URL")
  const serviceRoleKey = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")
  if (!supabaseUrl || !serviceRoleKey) return json({ ok: false, error: "config_missing" }, 503)

  // Authentication is enforced by the deployed Edge gateway
  // (verify_jwt=true). Both an authenticated Android Session JWT and a
  // scheduler service-role JWT may trigger this endpoint; the durable claim
  // RPC below applies the minimum refresh interval, while only the secret
  // kept in this function's environment can perform the privileged writes.

  let failureCode: SyncErrorCode = "database_unavailable"
  try {
    const claim = firstRow(await callRpc(supabaseUrl, serviceRoleKey, "claim", "claim_exchange_rate_sync", {
      p_min_interval_seconds: 7200,
    }))
    if (claim.claimed !== true) {
      return json({ ok: true, status: "skipped", next_attempt_at: claim.next_attempt_at ?? null })
    }

    let ecbResponse: Response
    try {
      ecbResponse = await fetch("https://www.ecb.europa.eu/stats/eurofxref/eurofxref-daily.xml", {
        headers: { accept: "application/xml,text/xml" },
      })
    } catch {
      throw new SyncFailure("upstream_unavailable")
    }
    if (!ecbResponse.ok) throw new SyncFailure("upstream_http_error")
    let xml: string
    try {
      xml = await ecbResponse.text()
    } catch {
      throw new SyncFailure("upstream_unavailable")
    }
    const payload = parseEcbXml(xml)
    const result = firstRow(await callRpc(supabaseUrl, serviceRoleKey, "replace", "replace_exchange_rate_cache", {
      p_ecb_date: payload.date,
      p_rates: payload.rates,
    }))
    return json({
      ok: true,
      status: "synced",
      currency_count: result.currency_count,
      pair_count: result.pair_count,
      observed_at: result.observed_at,
    })
  } catch (error) {
    failureCode = error instanceof SyncFailure ? error.code : "database_unavailable"
    try {
      await callRpc(supabaseUrl, serviceRoleKey, "failure", "record_exchange_rate_sync_failure", {
        p_error_code: failureCode,
      })
    } catch {
      // The original safe code is still returned; do not expose this failure.
    }
    console.error("sync-exchange-rates failed", failureCode)
    return json({ ok: false, error: failureCode }, 502)
  }
})
