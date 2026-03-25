import { createBot } from "./linktaxi/bot.js";
import { loadStore } from "./linktaxi/store.js";
import { getClient } from "./linktaxi/client.js";
import { startScheduler } from "./linktaxi/scheduler.js";

const BOT_TOKEN = process.env["LINKTAXI_BOT_TOKEN"];
const ADMIN_ID  = parseInt(process.env["LINKTAXI_ADMIN_ID"] ?? "0", 10);

if (!BOT_TOKEN) {
  console.error("❌  LINKTAXI_BOT_TOKEN is not set in .env");
  process.exit(1);
}
if (!ADMIN_ID) {
  console.error("❌  LINKTAXI_ADMIN_ID is not set in .env");
  process.exit(1);
}

console.log("🚕  Valkyrie_POSTER035 PRO starting…");
console.log(`ℹ️   Admin ID: ${ADMIN_ID}`);

const bot = createBot(BOT_TOKEN, ADMIN_ID);

// Try to restore a saved session + restart the scheduler automatically
(async () => {
  try {
    await getClient();
    console.log("✅  Session restored — GramJS connected.");
    const store = loadStore();
    if (store.schedule.intervalMs) {
      startScheduler({ intervalMs: store.schedule.intervalMs, getClient, bot, adminId: ADMIN_ID });
      console.log(`⏰  Scheduler restored (every ${store.schedule.intervalMs / 60000} min).`);
    }
  } catch {
    console.log("ℹ️   No saved session — send /start to the bot to authenticate.");
  }
})();

process.once("SIGINT",  () => bot.stop("SIGINT"));
process.once("SIGTERM", () => bot.stop("SIGTERM"));

bot.telegram.deleteWebhook({ drop_pending_updates: true })
  .then(() => {
    console.log("✅  Polling started — send /start to @your_bot");
    return bot.launch({ dropPendingUpdates: true });
  })
  .catch((err: Error) => {
    console.error("❌  Launch failed:", err.message);
    process.exit(1);
  });
