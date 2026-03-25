import { readdirSync, existsSync } from "fs";
import { resolve, dirname, extname } from "path";
import { fileURLToPath } from "url";

const __dir   = dirname(fileURLToPath(import.meta.url));
const IMG_DIR = resolve(__dir, "../../images");  // put images in /images folder

const EXTS = new Set([".jpg", ".jpeg", ".png", ".gif", ".webp", ".mp4"]);

export interface TaxiImage {
  index:    number;
  path:     string;
  filename: string;
  isVideo:  boolean;
}

export function listImages(): TaxiImage[] {
  if (!existsSync(IMG_DIR)) return [];
  return readdirSync(IMG_DIR)
    .filter((f) => EXTS.has(extname(f).toLowerCase()))
    .sort()
    .map((f, i) => ({
      index:    i + 1,
      path:     resolve(IMG_DIR, f),
      filename: f,
      isVideo:  extname(f).toLowerCase() === ".mp4",
    }));
}

export function getImage(n: number): TaxiImage | undefined {
  return listImages()[n - 1];
}
