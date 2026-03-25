import { TelegramClient, Api } from "telegram";
import { StringSession } from "telegram/sessions/index.js";
import { loadSession, saveSession, loadCredentials } from "./store.js";

// ── Module state ──────────────────────────────────────────────────────────────

let _client:        TelegramClient | null = null;
let _authed  = false;
let _phoneCodeHash: string | null = null;
let _phone:         string | null = null;
let _qrAbort:       (() => void) | null = null;

// ── Helpers ───────────────────────────────────────────────────────────────────

function getApiCredentials(): { apiId: number; apiHash: string } {
  const envId   = parseInt(process.env["LINKTAXI_API_ID"]   ?? "0", 10);
  const envHash = process.env["LINKTAXI_API_HASH"] ?? "";
  if (envId && envHash) return { apiId: envId, apiHash: envHash };

  const saved = loadCredentials();
  if (saved?.apiId && saved?.apiHash) return { apiId: saved.apiId, apiHash: saved.apiHash };

  throw new Error("No API credentials — set LINKTAXI_API_ID and LINKTAXI_API_HASH in .env");
}

async function buildClient(): Promise<TelegramClient> {
  const { apiId, apiHash } = getApiCredentials();
  const client = new TelegramClient(new StringSession(""), apiId, apiHash, {
    connectionRetries: 5,
    systemVersion: "Valkyrie/1.0",
  });
  await client.connect();
  return client;
}

// ── Public API ────────────────────────────────────────────────────────────────

export function isAuthenticated(): boolean {
  return _authed;
}

/** Get the authenticated GramJS client (restores saved session automatically). */
export async function getClient(): Promise<TelegramClient> {
  if (_client && _authed) return _client;

  const sessionStr = loadSession();
  if (!sessionStr) throw new Error("Not authenticated — send /start to the bot.");

  const { apiId, apiHash } = getApiCredentials();
  const client = new TelegramClient(new StringSession(sessionStr), apiId, apiHash, {
    connectionRetries: 5,
    systemVersion: "Valkyrie/1.0",
  });
  await client.connect();
  const me = await client.getMe();
  if (!me) throw new Error("Session invalid — log in again via the bot.");

  _client = client;
  _authed = true;
  return client;
}

// ── QR Code Login ─────────────────────────────────────────────────────────────

/**
 * Start QR-code-based login.
 * Polls every 5 s; calls onQrUrl with each new token image, onNeedPassword for 2FA,
 * onSuccess when fully logged in, onError on failure.
 */
export async function startQrLogin(opts: {
  onQrUrl:        (url: string) => Promise<void>;
  onNeedPassword: () => Promise<void>;
  onSuccess:      () => Promise<void>;
  onError:        (err: Error) => Promise<void>;
}): Promise<void> {
  if (_qrAbort) { _qrAbort(); _qrAbort = null; }
  if (_client)  { try { await _client.disconnect(); } catch { /* ignore */ } }

  const client = await buildClient();
  _client = client;
  _authed = false;
  _phoneCodeHash = null;

  const { apiId, apiHash } = getApiCredentials();
  let aborted = false;
  _qrAbort = () => { aborted = true; };

  const sleep = (ms: number) => new Promise<void>(r => setTimeout(r, ms));

  try {
    let currentTokenExpires = 0;

    while (!aborted) {
      let result;
      try {
        result = await client.invoke(
          new Api.auth.ExportLoginToken({ apiId, apiHash, exceptIds: [] })
        );
      } catch (invokeErr: unknown) {
        const msg = invokeErr instanceof Error ? invokeErr.message : String(invokeErr);
        if (msg.includes("SESSION_PASSWORD_NEEDED")) {
          _qrAbort = null;
          await opts.onNeedPassword();
          return;
        }
        throw invokeErr;
      }

      if (result instanceof Api.auth.LoginToken) {
        const tokenB64 = Buffer.from(result.token as Buffer).toString("base64url");
        const qrUrl    = `tg://login?token=${tokenB64}`;
        const expires  = result.expires as number;

        if (expires !== currentTokenExpires) {
          currentTokenExpires = expires;
          await opts.onQrUrl(qrUrl);
        }
        await sleep(5000);
        continue;
      }

      if (result instanceof Api.auth.LoginTokenMigrateTo) {
        console.log(`[client] QR: migrating to DC ${result.dcId}`);
        await client._switchDC(result.dcId);
        await client.invoke(new Api.auth.ImportLoginToken({ token: result.token }));
        continue;
      }

      if (result instanceof Api.auth.LoginTokenSuccess) {
        console.log("[client] QR: login confirmed.");
        await _finishAuth();
        _qrAbort = null;
        await opts.onSuccess();
        return;
      }

      await sleep(5000);
    }
  } catch (err: unknown) {
    if (!aborted) {
      await opts.onError(err instanceof Error ? err : new Error(String(err)));
    }
  }
}

export function cancelQrLogin(): void {
  if (_qrAbort) { _qrAbort(); _qrAbort = null; }
}

// ── Phone Code Login ──────────────────────────────────────────────────────────

/** Request a fresh login code to be sent to the user's Telegram app. */
export async function requestLoginCode(phone: string): Promise<void> {
  cancelQrLogin();
  if (_client) { try { await _client.disconnect(); } catch { /* ignore */ } _client = null; _authed = false; }

  const client = await buildClient();
  _client = client;
  _phone  = phone;

  const { apiId, apiHash } = getApiCredentials();
  const result = await client.invoke(
    new Api.auth.SendCode({ phoneNumber: phone, apiId, apiHash, settings: new Api.CodeSettings({}) })
  );
  _phoneCodeHash = (result as unknown as { phoneCodeHash: string }).phoneCodeHash;
  console.log(`[client] code sent — hash prefix: ${_phoneCodeHash?.slice(0, 8)}…`);
}

/** Submit the code from the user's Telegram app. Returns "ok" or "need_password". */
export async function submitLoginCode(code: string): Promise<"ok" | "need_password"> {
  if (!_client || !_phone || !_phoneCodeHash) throw new Error("No pending login — request a code first.");

  try {
    await _client.invoke(
      new Api.auth.SignIn({ phoneNumber: _phone, phoneCodeHash: _phoneCodeHash, phoneCode: code.trim() })
    );
  } catch (err: unknown) {
    const msg = err instanceof Error ? err.message : String(err);
    if (msg.includes("SESSION_PASSWORD_NEEDED")) return "need_password";
    throw err;
  }

  await _finishAuth();
  return "ok";
}

/** Submit the 2FA password. */
export async function submitLoginPassword(password: string): Promise<void> {
  if (!_client) throw new Error("No active session.");
  const { computeCheck } = await import("telegram/Password.js");
  const pwInfo = await _client.invoke(new Api.account.GetPassword());
  const check  = await computeCheck(pwInfo, password);
  await _client.invoke(new Api.auth.CheckPassword({ password: check }));
  await _finishAuth();
}

async function _finishAuth(): Promise<void> {
  if (!_client) throw new Error("No client.");
  _authed = true;
  saveSession((_client.session.save() as unknown) as string);
  console.log("[client] auth complete — session saved.");
}

export async function disconnectClient(): Promise<void> {
  cancelQrLogin();
  if (_client) { try { await _client.disconnect(); } catch { /* ignore */ } _client = null; _authed = false; }
}

export function isCodePending(): boolean {
  return _phoneCodeHash !== null && !_authed;
}
