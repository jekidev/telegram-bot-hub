import { readFileSync, writeFileSync, existsSync } from "fs";
import { resolve, dirname } from "path";
import { fileURLToPath } from "url";

const __dir = dirname(fileURLToPath(import.meta.url));

// All data files live next to the running script (project root)
const DATA_PATH    = resolve(__dir, "../../data.json");
const SESSION_PATH = resolve(__dir, "../../session.txt");
const CREDS_PATH   = resolve(__dir, "../../credentials.json");

// ── API Credentials ───────────────────────────────────────────────────────────

export interface Credentials {
  apiId:   number;
  apiHash: string;
  phone:   string;
}

export function loadCredentials(): Credentials | null {
  if (!existsSync(CREDS_PATH)) return null;
  try { return JSON.parse(readFileSync(CREDS_PATH, "utf8")) as Credentials; }
  catch { return null; }
}

export function saveCredentials(creds: Credentials): void {
  writeFileSync(CREDS_PATH, JSON.stringify(creds, null, 2), "utf8");
}

// ── Types ─────────────────────────────────────────────────────────────────────

export interface Link {
  url:      string;
  name:     string;
  emoji:    string;
  verified: boolean;
  addedAt:  string;
  chatId?:  string;
}

export interface Schedule {
  intervalMs:  number | null;
  imageIndex:  number;   // 0 = none, -1 = rotate, 1+ = fixed
  rotateIndex: number;
  lastRun:     string | null;
}

export interface Store {
  links:     Link[];
  blacklist: string[];
  schedule:  Schedule;
}

const DEFAULT_STORE: Store = {
  links:     [],
  blacklist: [],
  schedule:  { intervalMs: null, imageIndex: 0, rotateIndex: 0, lastRun: null },
};

// ── Load / Save ───────────────────────────────────────────────────────────────

export function loadStore(): Store {
  if (!existsSync(DATA_PATH)) return { ...DEFAULT_STORE };
  try {
    const raw = JSON.parse(readFileSync(DATA_PATH, "utf8")) as Partial<Store>;
    return {
      links:     raw.links     ?? [],
      blacklist: raw.blacklist ?? [],
      schedule:  { ...DEFAULT_STORE.schedule, ...raw.schedule },
    };
  } catch {
    return { ...DEFAULT_STORE };
  }
}

export function saveStore(store: Store): void {
  writeFileSync(DATA_PATH, JSON.stringify(store, null, 2), "utf8");
}

// ── Session ───────────────────────────────────────────────────────────────────

export function loadSession(): string {
  if (!existsSync(SESSION_PATH)) return process.env["LINKTAXI_SESSION"] ?? "";
  return readFileSync(SESSION_PATH, "utf8").trim();
}

export function saveSession(session: string): void {
  writeFileSync(SESSION_PATH, session, "utf8");
}

// ── Link helpers ──────────────────────────────────────────────────────────────

export function addLink(store: Store, url: string, name: string, emoji: string, chatId?: string): Store {
  if (store.links.some((l) => l.url === url)) return store;
  store.links.push({ url, name, emoji, verified: true, addedAt: new Date().toISOString(), chatId });
  saveStore(store);
  return store;
}

export function removeLink(store: Store, index: number): Store {
  store.links.splice(index, 1);
  saveStore(store);
  return store;
}

export function mergeScanned(store: Store, scanned: Pick<Link, "url" | "name" | "chatId">[]): { added: number; store: Store } {
  let added = 0;
  for (const s of scanned) {
    if (!store.links.some((l) => l.url === s.url)) {
      store.links.push({ url: s.url, name: s.name, emoji: "🔗", verified: true, addedAt: new Date().toISOString(), chatId: s.chatId });
      added++;
    }
  }
  if (added > 0) saveStore(store);
  return { added, store };
}

export function addBlacklist(store: Store, url: string): Store {
  if (!store.blacklist.includes(url)) { store.blacklist.push(url); saveStore(store); }
  return store;
}

export function removeBlacklist(store: Store, url: string): Store {
  store.blacklist = store.blacklist.filter((u) => u !== url);
  saveStore(store);
  return store;
}

export function setSchedule(store: Store, intervalMs: number | null): Store {
  store.schedule.intervalMs = intervalMs;
  saveStore(store);
  return store;
}

export function setScheduleImage(store: Store, imageIndex: number): Store {
  store.schedule.imageIndex = imageIndex;
  saveStore(store);
  return store;
}

export function recordRun(store: Store): Store {
  store.schedule.lastRun = new Date().toISOString();
  saveStore(store);
  return store;
}

export function nextRotateImage(store: Store, total: number): number {
  if (total === 0) return 0;
  const idx = (store.schedule.rotateIndex % total) + 1;
  store.schedule.rotateIndex = (store.schedule.rotateIndex + 1) % total;
  saveStore(store);
  return idx;
}

export function activeLinks(store: Store): Link[] {
  return store.links.filter((l) => !store.blacklist.includes(l.url));
}
