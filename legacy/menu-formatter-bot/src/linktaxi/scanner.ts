import { Api } from "telegram";
import type { TelegramClient } from "telegram";

// eslint-disable-next-line @typescript-eslint/no-explicit-any
type AnyInvite = any;

export interface ScannedLink {
  url:    string;
  name:   string;
  chatId: string;
}

const SLEEP = (ms: number) => new Promise((r) => setTimeout(r, ms));

export async function scanGroups(
  client: TelegramClient,
  onProgress?: (found: number, total: number) => void,
): Promise<ScannedLink[]> {
  const dialogs = await client.getDialogs({ limit: 500 });
  const results: ScannedLink[] = [];

  for (let i = 0; i < dialogs.length; i++) {
    const dialog = dialogs[i];
    const entity = dialog.entity;
    if (!entity) continue;
    if (entity instanceof Api.User) continue;

    const name   = dialog.title ?? "Unknown";
    const chatId = entity.id.toString();
    let   url: string | null = null;

    if (entity instanceof Api.Channel) {
      if (entity.username) {
        url = `https://t.me/${entity.username}`;
      } else {
        try {
          const res: AnyInvite = await client.invoke(
            new Api.messages.ExportChatInvite({ peer: await client.getInputEntity(entity.id) })
          );
          if (res?.link) url = res.link;
        } catch { /* skip */ }
        await SLEEP(400);
      }
    } else if (entity instanceof Api.Chat) {
      try {
        const res: AnyInvite = await client.invoke(
          new Api.messages.ExportChatInvite({ peer: await client.getInputEntity(entity.id) })
        );
        if (res?.link) url = res.link;
      } catch { /* skip */ }
      await SLEEP(300);
    }

    if (url) {
      results.push({ url, name, chatId });
      onProgress?.(results.length, dialogs.length);
    }
  }

  return results;
}
