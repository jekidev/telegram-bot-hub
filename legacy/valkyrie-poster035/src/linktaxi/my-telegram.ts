/**
 * my-telegram.ts
 * Automates the my.telegram.org login to retrieve API credentials.
 *
 * Flow:
 *   1. requestApiCode(phone)     → sends code to phone via my.telegram.org
 *   2. fetchApiCredentials(code) → logs in, returns { apiId, apiHash }
 */

interface PendingSetup { phone: string; randomHash: string; }
let _pending: PendingSetup | null = null;

const BASE    = "https://my.telegram.org";
const HEADERS = {
  "Content-Type": "application/x-www-form-urlencoded",
  "User-Agent":   "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120 Safari/537.36",
  "Origin":       BASE,
  "Referer":      `${BASE}/auth`,
};

export async function requestApiCode(phone: string): Promise<void> {
  _pending = null;
  const res  = await fetch(`${BASE}/auth/send_password`, {
    method: "POST", headers: HEADERS, body: new URLSearchParams({ phone }),
  });
  if (!res.ok) throw new Error(`my.telegram.org responded ${res.status}: ${await res.text()}`);
  const data = await res.json() as Record<string, unknown>;
  if (data["error"]) throw new Error(`my.telegram.org error: ${data["error"]}`);
  const randomHash = String(data["random_hash"] ?? "");
  if (!randomHash) throw new Error("No random_hash returned — check phone number format.");
  _pending = { phone, randomHash };
}

export async function fetchApiCredentials(code: string): Promise<{ apiId: number; apiHash: string }> {
  if (!_pending) throw new Error("No pending setup — call requestApiCode first.");
  const { phone, randomHash } = _pending;

  const loginRes = await fetch(`${BASE}/auth/login`, {
    method: "POST", headers: HEADERS,
    body: new URLSearchParams({ phone, random_hash: randomHash, password: code.trim() }),
    redirect: "manual",
  });

  let rawCookies: string[] = [];
  if (typeof (loginRes.headers as unknown as Record<string, unknown>)["getSetCookie"] === "function") {
    rawCookies = (loginRes.headers as unknown as { getSetCookie(): string[] }).getSetCookie();
  } else {
    const single = loginRes.headers.get("set-cookie");
    if (single) rawCookies = [single];
  }
  const cookieStr = rawCookies.map((c) => c.split(";")[0]).join("; ");
  const authHeaders = { ...HEADERS, Cookie: cookieStr };

  let appsHtml = await (await fetch(`${BASE}/apps`, { headers: authHeaders })).text();
  let creds    = parseCredentials(appsHtml);

  if (!creds) {
    await createApp(cookieStr, authHeaders, appsHtml);
    appsHtml = await (await fetch(`${BASE}/apps`, { headers: authHeaders })).text();
    creds    = parseCredentials(appsHtml);
  }

  if (!creds) throw new Error("Could not extract api_id/api_hash from my.telegram.org.");
  _pending = null;
  return creds;
}

function parseCredentials(html: string): { apiId: number; apiHash: string } | null {
  const idMatch   = html.match(/App api_id:[\s\S]{0,400}?<strong>(\d+)<\/strong>/i);
  const hashMatch = html.match(/App api_hash:[\s\S]{0,400}?uneditable-input[^>]*>\s*([a-f0-9]{32})\s*</i)
                 ?? html.match(/App api_hash:[\s\S]{0,400}?>([a-f0-9]{32})</i);
  if (idMatch && hashMatch) return { apiId: parseInt(idMatch[1], 10), apiHash: hashMatch[1] };

  const idInput   = html.match(/name=["']?app_id["']?[^>]*value=["']?(\d+)/i)   ?? html.match(/value=["']?(\d+)["']?[^>]*name=["']?app_id["']?/i);
  const hashInput = html.match(/name=["']?app_hash["']?[^>]*value=["']?([a-f0-9]{32})/i) ?? html.match(/value=["']?([a-f0-9]{32})["']?[^>]*name=["']?app_hash["']?/i);
  if (idInput && hashInput) return { apiId: parseInt(idInput[1], 10), apiHash: hashInput[1] };

  const idJs   = html.match(/['"](app_id|api_id)['"]\s*:\s*['"]?(\d+)/i);
  const hashJs = html.match(/['"](app_hash|api_hash)['"]\s*:\s*['"]([a-f0-9]{32})/i);
  if (idJs && hashJs) return { apiId: parseInt(idJs[2], 10), apiHash: hashJs[2] };

  return null;
}

async function createApp(cookie: string, headers: Record<string, string>, appsHtml: string): Promise<void> {
  const hashMatch = appsHtml.match(/name=["']?hash["']?\s+value=["']?([a-f0-9]+)["']?/i);
  await fetch(`${BASE}/apps/create`, {
    method: "POST",
    headers: { ...headers, Cookie: cookie },
    body: new URLSearchParams({
      hash: hashMatch?.[1] ?? "",
      app_title: "My App", app_shortname: "myapp",
      app_url: "", app_platform: "other", app_desc: "",
    }),
  });
}

export function hasPendingSetup(): boolean { return _pending !== null; }
export function pendingPhone(): string | null { return _pending?.phone ?? null; }
