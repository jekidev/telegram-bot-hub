import { Telegraf, Markup } from "telegraf";
import { readFileSync } from "fs";

import {
  loadStore, saveStore, addLink, removeLink, mergeScanned,
  addBlacklist, removeBlacklist, setSchedule, setScheduleImage,
  activeLinks, saveCredentials, loadCredentials,
} from "./store.js";
import {
  requestLoginCode, submitLoginCode, submitLoginPassword,
  startQrLogin, cancelQrLogin,
  getClient, isAuthenticated,
} from "./client.js";
import { requestApiCode, fetchApiCredentials } from "./my-telegram.js";
import { scanGroups } from "./scanner.js";
import { formatPost } from "./formatter.js";
import { listImages, getImage } from "./images.js";
import {
  startScheduler, stopScheduler, isSchedulerRunning,
  runPost, parseInterval, formatInterval,
} from "./scheduler.js";

// ── State machine ─────────────────────────────────────────────────────────────
type BotState =
  | { type: "idle" }
  | { type: "waiting_phone" }
  | { type: "waiting_apicode"; phone: string }
  | { type: "waiting_tg_code" }
  | { type: "waiting_2fa" }
  | { type: "waiting_qr" };

let _state: BotState = { type: "idle" };

// ── Keyboards ─────────────────────────────────────────────────────────────────
const KB = {
  setupStart: Markup.inlineKeyboard([
    [Markup.button.callback("🚀 Begin Setup", "setup_start")],
  ]),

  mainMenu: Markup.inlineKeyboard([
    [
      Markup.button.callback("🔍 Scan Groups",  "scan"),
      Markup.button.callback("📋 View Links",   "links_1"),
    ],
    [
      Markup.button.callback("📤 Post Now",     "post_now"),
      Markup.button.callback("👁 Preview Post", "preview"),
    ],
    [
      Markup.button.callback("⏰ Schedule",     "schedule_menu"),
      Markup.button.callback("⛔ Blacklist",    "bl_show"),
    ],
    [
      Markup.button.callback("🖼 Images",       "images"),
      Markup.button.callback("📊 Status",       "status"),
    ],
  ]),

  scheduleMenu: Markup.inlineKeyboard([
    [
      Markup.button.callback("30m",  "sched_30m"),
      Markup.button.callback("1h",   "sched_1h"),
      Markup.button.callback("2h",   "sched_2h"),
      Markup.button.callback("4h",   "sched_4h"),
    ],
    [
      Markup.button.callback("6h",   "sched_6h"),
      Markup.button.callback("12h",  "sched_12h"),
      Markup.button.callback("24h",  "sched_24h"),
      Markup.button.callback("⏹ Stop", "sched_off"),
    ],
    [Markup.button.callback("« Back", "main_menu")],
  ]),

  cancel: Markup.inlineKeyboard([
    [Markup.button.callback("❌ Cancel", "cancel")],
  ]),

  backToMain: Markup.inlineKeyboard([
    [Markup.button.callback("« Main Menu", "main_menu")],
  ]),

  connectTelegram: Markup.inlineKeyboard([
    [Markup.button.callback("🔲 Login via QR Code (recommended)", "qr_login")],
    [Markup.button.callback("📲 Login via Phone Code", "setup_tg_login")],
    [Markup.button.callback("🔄 Change phone / credentials", "setup_start")],
  ]),

  resendCode: Markup.inlineKeyboard([
    [Markup.button.callback("🔁 Resend Code", "resend_code")],
    [Markup.button.callback("❌ Cancel", "cancel_auth")],
  ]),
};

// ── Factory ───────────────────────────────────────────────────────────────────
export function createBot(token: string, adminId: number): Telegraf {
  const bot = new Telegraf(token);

  // Admin gate — only the owner can use this bot
  bot.use(async (ctx, next) => {
    if (ctx.from?.id !== adminId) return;
    return next();
  });

  function notify(text: string, extra?: object) {
    return bot.telegram.sendMessage(adminId, text, extra);
  }

  let _authPhone = "";

  async function sendTelegramCode(phone: string): Promise<void> {
    _authPhone = phone;
    _state     = { type: "waiting_tg_code" };
    await requestLoginCode(phone);
    await notify(
      "📲 A login code was just sent to your Telegram app.\n\n" +
      "Open Telegram, find the newest message from the official Telegram account, and type the code here:"
    );
  }

  async function showMainMenu(prefix = "") {
    const store    = loadStore();
    const active   = activeLinks(store);
    const sched    = store.schedule;
    const schedStr = sched.intervalMs && isSchedulerRunning()
      ? `⏰ Every ${formatInterval(sched.intervalMs)}`
      : sched.intervalMs ? `⏸ ${formatInterval(sched.intervalMs)} (paused)` : "⏹ Off";

    await bot.telegram.sendMessage(
      adminId,
      `🚕 *Valkyrie_POSTER035 PRO*\n${prefix ? prefix + "\n" : ""}\n` +
      `📋 ${store.links.length} links (${active.length} active)\n${schedStr}`,
      { parse_mode: "Markdown", ...KB.mainMenu }
    );
  }

  // ── /start ───────────────────────────────────────────────────────────────────
  bot.command("start", async (ctx) => {
    try {
      if (isAuthenticated()) {
        await showMainMenu("✅ Account connected");
      } else {
        const saved = loadCredentials();
        if (saved) {
          await ctx.reply(
            `🚕 *Valkyrie_POSTER035 PRO*\n\n📱 Account: ${saved.phone}\n\n` +
            `Tap a button below to connect your Telegram account.`,
            { parse_mode: "Markdown", ...KB.connectTelegram }
          );
        } else {
          await ctx.reply(
            "🚕 *Valkyrie_POSTER035 PRO*\n\n" +
            "Welcome! Tap below to set up your Telegram account connection.",
            { parse_mode: "Markdown", ...KB.setupStart }
          );
        }
      }
    } catch (err) {
      console.error("❌ /start error:", err);
    }
  });

  // ── Setup flow ────────────────────────────────────────────────────────────────
  bot.action("setup_start", async (ctx) => {
    await ctx.answerCbQuery();
    _state = { type: "waiting_phone" };
    await ctx.editMessageText(
      "📱 *Step 1 of 3 — Phone Number*\n\nSend your phone number with country code:\n_Example: +4512345678_",
      { parse_mode: "Markdown", ...KB.cancel }
    );
  });

  bot.action("cancel", async (ctx) => {
    await ctx.answerCbQuery();
    _state = { type: "idle" };
    await ctx.editMessageText("❌ Cancelled.", KB.setupStart);
  });

  bot.action("setup_tg_login", async (ctx) => {
    await ctx.answerCbQuery();
    const saved = loadCredentials();
    if (!saved) { await ctx.editMessageText("No credentials — do Full Setup first.", KB.setupStart); return; }
    await ctx.editMessageText(`📲 Sending code to ${saved.phone}…`);
    try {
      await sendTelegramCode(saved.phone);
    } catch (err: unknown) {
      _state = { type: "idle" };
      await notify(`❌ Failed: ${err instanceof Error ? err.message : String(err)}`, KB.connectTelegram);
    }
  });

  bot.action("resend_code", async (ctx) => {
    await ctx.answerCbQuery();
    if (!_authPhone) { await ctx.reply("No active login.", KB.connectTelegram); return; }
    await ctx.reply(`🔁 Sending fresh code to ${_authPhone}…`);
    try { await sendTelegramCode(_authPhone); }
    catch (err: unknown) {
      _state = { type: "idle" };
      await notify(`❌ Resend failed: ${err instanceof Error ? err.message : String(err)}`, KB.connectTelegram);
    }
  });

  bot.action("cancel_auth", async (ctx) => {
    await ctx.answerCbQuery();
    cancelQrLogin();
    _state = { type: "idle" }; _authPhone = "";
    await ctx.reply("❌ Login cancelled.", KB.connectTelegram);
  });

  // ── QR Code Login ─────────────────────────────────────────────────────────────
  bot.action("qr_login", async (ctx) => {
    await ctx.answerCbQuery();
    if (!loadCredentials()) { await ctx.reply("No credentials — do Full Setup first.", KB.setupStart); return; }

    _state = { type: "waiting_qr" };
    await ctx.reply(
      "🔲 Starting QR login…\n\n" +
      "On your phone: Settings → Privacy & Security → Active Sessions → Link Desktop Device\n\n" +
      "Scan the QR code I'll send:"
    );

    const cancelKb = Markup.inlineKeyboard([[Markup.button.callback("❌ Cancel", "cancel_auth")]]);
    const { default: QRCode } = await import("qrcode");

    await startQrLogin({
      onQrUrl: async (url) => {
        const png = await QRCode.toBuffer(url, { type: "png", width: 512, margin: 2 });
        await bot.telegram.sendPhoto(adminId, { source: png }, {
          caption: "📷 Scan in Telegram:\nSettings → Privacy & Security → Active Sessions → Link Desktop Device\n\nRefreshes automatically if it expires.",
          ...cancelKb,
        });
      },
      onNeedPassword: async () => {
        _state = { type: "waiting_2fa" };
        await notify("🔐 2FA is enabled.\n\nType your Two-Step Verification password:");
      },
      onSuccess: async () => {
        _state = { type: "idle" };
        const store = loadStore();
        if (store.schedule.intervalMs) startScheduler({ intervalMs: store.schedule.intervalMs, getClient, bot, adminId });
        await showMainMenu("✅ QR login successful! Account connected.");
      },
      onError: async (err) => {
        _state = { type: "idle" };
        await notify(`❌ QR login failed: ${err.message}`, KB.connectTelegram);
      },
    });
  });

  bot.action("main_menu", async (ctx) => {
    await ctx.answerCbQuery();
    await ctx.deleteMessage().catch(() => {});
    await showMainMenu();
  });

  // ── Scan ──────────────────────────────────────────────────────────────────────
  bot.action("scan", async (ctx) => {
    await ctx.answerCbQuery();
    if (!isAuthenticated()) { await ctx.reply("❌ Not connected.", KB.setupStart); return; }
    const msg = await ctx.reply("🔍 Scanning groups… (this may take a minute)");
    let found = 0;
    try {
      const client  = await getClient();
      const scanned = await scanGroups(client, async (f) => {
        found = f;
        await bot.telegram.editMessageText(ctx.chat!.id, msg.message_id, undefined,
          `🔍 Scanning… ${found} links found`).catch(() => {});
      });
      const store = loadStore();
      const { added } = mergeScanned(store, scanned);
      await bot.telegram.editMessageText(ctx.chat!.id, msg.message_id, undefined,
        `✅ Scan complete! ${scanned.length} found — ${added} new. Total: ${store.links.length}`
      ).catch(() => {});
      await showMainMenu();
    } catch (err: unknown) {
      await ctx.reply(`❌ Scan failed: ${err instanceof Error ? err.message : String(err)}`);
    }
  });

  // ── Links ─────────────────────────────────────────────────────────────────────
  const PAGE = 10;

  async function showLinks(chatId: number, page: number) {
    const store = loadStore();
    if (!store.links.length) { await bot.telegram.sendMessage(chatId, "No links — scan first.", KB.backToMain); return; }
    const total = Math.ceil(store.links.length / PAGE);
    const slice = store.links.slice((page - 1) * PAGE, page * PAGE);
    const lines = slice.map((l, i) => {
      const n  = (page - 1) * PAGE + i + 1;
      const bl = store.blacklist.includes(l.url) ? " ⛔" : "";
      return `${n}. ${l.emoji} *${l.name}*${bl}\n   ${l.url}`;
    });
    const nav: ReturnType<typeof Markup.button.callback>[] = [];
    if (page > 1)     nav.push(Markup.button.callback("◀ Prev", `links_${page - 1}`));
    if (page < total) nav.push(Markup.button.callback("Next ▶", `links_${page + 1}`));
    const kb = Markup.inlineKeyboard([nav.length ? nav : [], [Markup.button.callback("« Back", "main_menu")]]);
    await bot.telegram.sendMessage(chatId, lines.join("\n\n") + `\n\nPage ${page}/${total}`, { parse_mode: "Markdown", ...kb });
  }

  for (let p = 1; p <= 50; p++) {
    bot.action(`links_${p}`, async (ctx) => {
      await ctx.answerCbQuery();
      await ctx.deleteMessage().catch(() => {});
      await showLinks(ctx.chat!.id, p);
    });
  }

  // ── Blacklist ─────────────────────────────────────────────────────────────────
  bot.action("bl_show", async (ctx) => {
    await ctx.answerCbQuery();
    const store = loadStore();
    if (!store.blacklist.length) {
      await ctx.reply("⛔ Blacklist is empty.\n\nUse `/bl add <url or number>` to add.", { parse_mode: "Markdown", ...KB.backToMain });
      return;
    }
    const lines = store.blacklist.map((u, i) => `${i + 1}. ${u}`);
    await ctx.reply("⛔ *Blacklisted:*\n\n" + lines.join("\n") + "\n\nRemove: `/bl remove <number>`", { parse_mode: "Markdown", ...KB.backToMain });
  });

  // ── Schedule ──────────────────────────────────────────────────────────────────
  bot.action("schedule_menu", async (ctx) => {
    await ctx.answerCbQuery();
    const store  = loadStore();
    const sched  = store.schedule;
    const status = sched.intervalMs
      ? `Currently: every ${formatInterval(sched.intervalMs)} — ${isSchedulerRunning() ? "🟢 running" : "🔴 paused"}`
      : "Currently: off";
    await ctx.editMessageText(`⏰ *Schedule*\n\n${status}\n\nPick an interval:`, { parse_mode: "Markdown", ...KB.scheduleMenu });
  });

  const INTERVALS: Record<string, string> = {
    sched_30m: "30m", sched_1h: "1h", sched_2h: "2h",
    sched_4h: "4h",  sched_6h: "6h", sched_12h: "12h", sched_24h: "24h",
  };

  for (const [action, label] of Object.entries(INTERVALS)) {
    bot.action(action, async (ctx) => {
      await ctx.answerCbQuery();
      if (!isAuthenticated()) { await ctx.reply("❌ Not connected.", KB.setupStart); return; }
      const ms = parseInterval(label)!;
      setSchedule(loadStore(), ms);
      startScheduler({ intervalMs: ms, getClient, bot, adminId });
      await ctx.editMessageText(`✅ Scheduled: every *${label}*.`, { parse_mode: "Markdown", ...KB.backToMain });
    });
  }

  bot.action("sched_off", async (ctx) => {
    await ctx.answerCbQuery();
    stopScheduler();
    setSchedule(loadStore(), null);
    await ctx.editMessageText("⏹ Schedule stopped.", KB.backToMain);
  });

  // ── Preview ───────────────────────────────────────────────────────────────────
  bot.action("preview", async (ctx) => {
    await ctx.answerCbQuery();
    const store = loadStore();
    const links = activeLinks(store);
    const post  = formatPost(links);
    await ctx.reply(`📋 *Preview* (${links.length} links)\n\n` + post, { parse_mode: "Markdown", ...KB.backToMain });
  });

  // ── Images ────────────────────────────────────────────────────────────────────
  bot.action("images", async (ctx) => {
    await ctx.answerCbQuery();
    const images = listImages();
    if (!images.length) { await ctx.reply("No images in /images folder.", KB.backToMain); return; }
    const btns = images.map((img) => Markup.button.callback(`${img.index}. ${img.filename}`, `setimg_${img.index}`));
    const rows: (typeof btns[0])[][] = [];
    for (let i = 0; i < btns.length; i += 3) rows.push(btns.slice(i, i + 3));
    rows.push([Markup.button.callback("🔄 Rotate all", "setimg_rotate"), Markup.button.callback("🚫 No image", "setimg_none")]);
    rows.push([Markup.button.callback("« Back", "main_menu")]);
    await ctx.editMessageText("🖼 *Choose image for posts:*", { parse_mode: "Markdown", ...Markup.inlineKeyboard(rows) });
  });

  bot.action("setimg_rotate", async (ctx) => {
    await ctx.answerCbQuery();
    setScheduleImage(loadStore(), -1);
    await ctx.editMessageText("🔄 Rotating through all images.", KB.backToMain);
  });

  bot.action("setimg_none", async (ctx) => {
    await ctx.answerCbQuery();
    setScheduleImage(loadStore(), 0);
    await ctx.editMessageText("🚫 Text-only posts.", KB.backToMain);
  });

  for (let n = 1; n <= 20; n++) {
    bot.action(`setimg_${n}`, async (ctx) => {
      await ctx.answerCbQuery();
      const images = listImages();
      setScheduleImage(loadStore(), n);
      await ctx.editMessageText(`🖼 Fixed image: ${images[n - 1]?.filename ?? n}`, KB.backToMain);
    });
  }

  // ── Post Now ──────────────────────────────────────────────────────────────────
  bot.action("post_now", async (ctx) => {
    await ctx.answerCbQuery();
    if (!isAuthenticated()) { await ctx.reply("❌ Not connected.", KB.setupStart); return; }
    const store  = loadStore();
    const active = activeLinks(store);
    if (!active.length) { await ctx.reply("No active links — scan first.", KB.backToMain); return; }
    const images = listImages();
    if (images.length > 0) {
      const btns = images.map((img) => Markup.button.callback(`${img.index}`, `postwith_${img.index}`));
      const rows: (typeof btns[0])[][] = [];
      for (let i = 0; i < btns.length; i += 5) rows.push(btns.slice(i, i + 5));
      rows.push([Markup.button.callback("No image — text only", "postwith_0")]);
      rows.push([Markup.button.callback("« Back", "main_menu")]);
      await ctx.editMessageText(`📤 *Post to ${active.length} groups* — pick image:`, { parse_mode: "Markdown", ...Markup.inlineKeyboard(rows) });
    } else {
      await ctx.editMessageText(`📤 Posting to ${active.length} groups…`);
      await doPost(ctx.chat!.id, 0, active.length);
    }
  });

  for (let n = 0; n <= 20; n++) {
    bot.action(`postwith_${n}`, async (ctx) => {
      await ctx.answerCbQuery();
      const active = activeLinks(loadStore());
      await ctx.editMessageText(`📤 Posting to ${active.length} groups…`);
      await doPost(ctx.chat!.id, n, active.length);
    });
  }

  async function doPost(chatId: number, imageIndex: number, groupCount: number) {
    try {
      const store = loadStore();
      store.schedule.imageIndex = imageIndex;
      const { sent, failed, skipped } = await runPost(getClient);
      await bot.telegram.sendMessage(chatId,
        `✅ Done! ${groupCount} groups targeted.\n\nSent: ${sent} · Failed: ${failed} · Skipped: ${skipped}`,
        KB.mainMenu
      );
    } catch (err: unknown) {
      await bot.telegram.sendMessage(chatId, `❌ Post failed: ${err instanceof Error ? err.message : String(err)}`, KB.mainMenu);
    }
  }

  // ── Status ────────────────────────────────────────────────────────────────────
  bot.action("status", async (ctx) => {
    await ctx.answerCbQuery();
    const store  = loadStore();
    const active = activeLinks(store);
    const sched  = store.schedule;
    const images = listImages();
    await ctx.reply(
      `📊 *Status*\n\n` +
      `🔐 GramJS: ${isAuthenticated() ? "✅ Connected" : "❌ Not connected"}\n` +
      `📋 Links: ${store.links.length} total, ${active.length} active, ${store.blacklist.length} blacklisted\n` +
      `🖼 Images: ${images.length} found\n` +
      `⏰ Scheduler: ${sched.intervalMs ? `every ${formatInterval(sched.intervalMs)} (${isSchedulerRunning() ? "running" : "paused"})` : "off"}\n` +
      `🕐 Last run: ${sched.lastRun ? new Date(sched.lastRun).toLocaleString() : "never"}`,
      { parse_mode: "Markdown", ...KB.backToMain }
    );
  });

  // ── Text / state machine ──────────────────────────────────────────────────────
  bot.on("message", async (ctx) => {
    const text = (ctx.message as { text?: string }).text?.trim() ?? "";
    if (!text) return;

    // ── Slash commands first ──────────────────────────────────────────────────
    if (text.startsWith("/bl ")) {
      const [, cmd, ...rest] = text.split(" ");
      const store = loadStore();
      if (cmd === "add") {
        const arg = rest.join(" ").trim();
        const n   = parseInt(arg, 10);
        const url = (!isNaN(n) && store.links[n - 1]) ? store.links[n - 1].url : arg;
        addBlacklist(store, url);
        await ctx.reply(`⛔ Blacklisted: ${url}`, KB.backToMain);
      } else if (cmd === "remove") {
        const n = parseInt(rest.join(""), 10) - 1;
        const url = store.blacklist[n];
        if (url) { removeBlacklist(store, url); await ctx.reply(`✅ Removed: ${url}`, KB.backToMain); }
        else await ctx.reply("Not found.", KB.backToMain);
      }
      return;
    }

    if (text.startsWith("/add ")) {
      const parts = text.slice(5).trim().split(/\s+/);
      const url   = parts[0] ?? "";
      const emoji = parts[1] ?? "🔗";
      const name  = parts.slice(2).join(" ") || url;
      if (!url.startsWith("http")) { await ctx.reply("Usage: /add <url> [emoji] [name]"); return; }
      const store = loadStore();
      addLink(store, url, name, emoji);
      await ctx.reply(`✅ Added: ${name} ${emoji}`, KB.mainMenu);
      return;
    }

    if (text.startsWith("/remove ")) {
      const n = parseInt(text.slice(8).trim(), 10) - 1;
      const store = loadStore();
      if (n < 0 || n >= store.links.length) { await ctx.reply("Invalid number."); return; }
      const removed = store.links[n];
      removeLink(store, n);
      await ctx.reply(`✅ Removed: ${removed.name}`, KB.mainMenu);
      return;
    }

    // ── State machine ─────────────────────────────────────────────────────────
    switch (_state.type) {
      case "waiting_phone": {
        const phone = text.startsWith("+") ? text : `+${text}`;
        _state = { type: "idle" };
        await ctx.reply("⏳ Requesting API code from my.telegram.org…");
        try {
          await requestApiCode(phone);
          _state = { type: "waiting_apicode", phone };
          await ctx.reply(
            "📩 *Step 2 of 3 — my.telegram.org Code*\n\n" +
            "A code was sent to your Telegram app. Type it here:",
            { parse_mode: "Markdown", ...KB.cancel }
          );
        } catch (err: unknown) {
          await ctx.reply(`❌ Failed: ${err instanceof Error ? err.message : String(err)}`, KB.setupStart);
        }
        break;
      }

      case "waiting_apicode": {
        const code  = text;
        const phone = _state.phone;
        _state = { type: "idle" };
        await ctx.reply("⏳ Verifying with my.telegram.org…");
        try {
          const { apiId, apiHash } = await fetchApiCredentials(code);
          saveCredentials({ apiId, apiHash, phone });
          await ctx.reply("✅ API credentials saved!\n\nSending Telegram login code…");
          try { await sendTelegramCode(phone); }
          catch (err: unknown) {
            _state = { type: "idle" };
            await ctx.reply(`❌ Code send failed: ${err instanceof Error ? err.message : String(err)}`, KB.connectTelegram);
          }
        } catch (err: unknown) {
          _state = { type: "waiting_apicode", phone };
          await ctx.reply(`❌ Invalid code: ${err instanceof Error ? err.message : String(err)}\n\nTry again:`);
        }
        break;
      }

      case "waiting_tg_code": {
        await ctx.reply("⏳ Verifying code…");
        try {
          const result = await submitLoginCode(text);
          if (result === "need_password") {
            _state = { type: "waiting_2fa" };
            await notify("🔐 2FA enabled — type your Two-Step Verification password:");
          } else {
            _state = { type: "idle" };
            const store = loadStore();
            if (store.schedule.intervalMs) startScheduler({ intervalMs: store.schedule.intervalMs, getClient, bot, adminId });
            await showMainMenu("✅ Account connected!");
          }
        } catch (err: unknown) {
          const msg = err instanceof Error ? err.message : String(err);
          if (msg.includes("PHONE_CODE_INVALID")) {
            await notify("❌ Wrong code — check and retype it, or get a fresh one.", KB.resendCode);
          } else if (msg.includes("PHONE_CODE_EXPIRED")) {
            await notify("⏰ Code expired — tap Resend to get a fresh one.", KB.resendCode);
          } else {
            _state = { type: "idle" };
            await notify(`❌ Error: ${msg}`, KB.connectTelegram);
          }
        }
        break;
      }

      case "waiting_2fa": {
        await ctx.reply("⏳ Verifying password…");
        try {
          await submitLoginPassword(text);
          _state = { type: "idle" };
          const store = loadStore();
          if (store.schedule.intervalMs) startScheduler({ intervalMs: store.schedule.intervalMs, getClient, bot, adminId });
          await showMainMenu("✅ Connected with 2FA!");
        } catch (err: unknown) {
          await notify(`❌ 2FA error: ${err instanceof Error ? err.message : String(err)}\n\nTry again:`);
        }
        break;
      }

      default: {
        if (isAuthenticated()) await showMainMenu();
        else await ctx.reply("Tap the button to connect:", KB.setupStart);
      }
    }
  });

  // ── Slash command aliases ─────────────────────────────────────────────────────
  bot.command("setup", async (ctx) => {
    _state = { type: "waiting_phone" };
    await ctx.reply("📱 *Step 1 — Phone Number*\n\nSend your number with country code:", { parse_mode: "Markdown", ...KB.cancel });
  });

  bot.command("auth", async (ctx) => {
    const saved = loadCredentials();
    if (!saved) { await ctx.reply("No credentials — use /setup first."); return; }
    await ctx.reply(`📱 Sending code to ${saved.phone}…`);
    try { await sendTelegramCode(saved.phone); }
    catch (err: unknown) {
      _state = { type: "idle" };
      await ctx.reply(`❌ Failed: ${err instanceof Error ? err.message : String(err)}`, KB.connectTelegram);
    }
  });

  bot.command("scan", async (ctx) => {
    if (!isAuthenticated()) { await ctx.reply("❌ Not connected.", KB.setupStart); return; }
    const msg = await ctx.reply("🔍 Scanning…");
    try {
      const client  = await getClient();
      const scanned = await scanGroups(client);
      const store   = loadStore();
      const { added } = mergeScanned(store, scanned);
      await bot.telegram.editMessageText(ctx.chat.id, msg.message_id, undefined,
        `✅ ${scanned.length} links found — ${added} new added.`
      ).catch(() => {});
      await showMainMenu();
    } catch (err: unknown) {
      await ctx.reply(`❌ ${err instanceof Error ? err.message : String(err)}`);
    }
  });

  bot.command("post", async (ctx) => {
    if (!isAuthenticated()) { await ctx.reply("❌ Not connected."); return; }
    await ctx.reply("📤 Posting now…");
    try {
      const { sent, failed, skipped } = await runPost(getClient);
      await ctx.reply(`✅ Done — ${sent} sent, ${failed} failed, ${skipped} skipped.`);
    } catch (err: unknown) {
      await ctx.reply(`❌ ${err instanceof Error ? err.message : String(err)}`);
    }
  });

  return bot;
}
