import { readFileSync } from "fs";
import type { Telegraf } from "telegraf";
import type { TelegramClient } from "telegram";
import { loadStore, activeLinks, nextRotateImage, recordRun, type Link } from "./store.js";
import { formatPost } from "./formatter.js";
import { listImages, getImage } from "./images.js";

function peerFor(link: Link): string | number {
  const pub = link.url.match(/^https:\/\/t\.me\/([a-zA-Z][a-zA-Z0-9_]{4,})$/);
  if (pub) return pub[1];
  if (link.chatId) return parseInt(link.chatId, 10);
  return link.url;
}

let _timer:     ReturnType<typeof setInterval> | null = null;
let _adminId:   number | string = 0;
let _bot:       Telegraf | null = null;

const SLEEP = (ms: number) => new Promise((r) => setTimeout(r, ms));

export async function runPost(
  getClient: () => Promise<TelegramClient>
): Promise<{ sent: number; failed: number; skipped: number }> {
  const store  = loadStore();
  const links  = activeLinks(store);
  const post   = formatPost(links);
  const images = listImages();

  let imageIndex = store.schedule.imageIndex;
  if (imageIndex === -1) imageIndex = nextRotateImage(store, images.length);
  const img = imageIndex > 0 ? getImage(imageIndex) : undefined;

  let sent = 0, failed = 0, skipped = 0;
  const client = await getClient();

  await client.getDialogs({ limit: 500 }).catch(() => {});

  for (const link of links) {
    if (!link.chatId) { skipped++; continue; }
    try {
      const peer = await client.getInputEntity(peerFor(link));
      if (img) {
        const fileBytes = readFileSync(img.path);
        await client.sendFile(peer, { file: fileBytes, caption: post, forceDocument: false });
      } else {
        await client.sendMessage(peer, { message: post });
      }
      sent++;
    } catch { failed++; }
    await SLEEP(1500);
  }

  recordRun(store);
  return { sent, failed, skipped };
}

export function startScheduler(opts: {
  intervalMs: number;
  getClient:  () => Promise<TelegramClient>;
  bot:        Telegraf;
  adminId:    number | string;
}): void {
  stopScheduler();
  _bot     = opts.bot;
  _adminId = opts.adminId;

  _timer = setInterval(async () => {
    try {
      await notify("⏰ Scheduled post starting…");
      const { sent, failed, skipped } = await runPost(opts.getClient);
      await notify(`✅ Done — ${sent} sent, ${failed} failed, ${skipped} skipped.`);
    } catch (err: unknown) {
      await notify(`❌ Scheduled post failed: ${err instanceof Error ? err.message : String(err)}`);
    }
  }, opts.intervalMs);
}

export function stopScheduler(): void {
  if (_timer !== null) { clearInterval(_timer); _timer = null; }
}

export function isSchedulerRunning(): boolean {
  return _timer !== null;
}

async function notify(text: string): Promise<void> {
  if (_bot && _adminId) {
    try { await _bot.telegram.sendMessage(_adminId, text); } catch { /* swallow */ }
  }
}

export function parseInterval(str: string): number | null {
  const s = str.trim().toLowerCase();
  const mH = s.match(/^(\d+)h$/);
  const mM = s.match(/^(\d+)m$/);
  const mB = s.match(/^(\d+)h(\d+)m$/);
  if (mH) return parseInt(mH[1], 10) * 3_600_000;
  if (mM) return parseInt(mM[1], 10) *    60_000;
  if (mB) return (parseInt(mB[1], 10) * 3600 + parseInt(mB[2], 10) * 60) * 1000;
  return null;
}

export function formatInterval(ms: number): string {
  const h = Math.floor(ms / 3_600_000);
  const m = Math.floor((ms % 3_600_000) / 60_000);
  if (h > 0 && m > 0) return `${h}h ${m}m`;
  if (h > 0)           return `${h}h`;
  return `${m}m`;
}
