import type { Link } from "./store.js";

// Mathematical Sans-Serif Unicode block
const SANS_UP = 0x1d5a0;
const SANS_LO = 0x1d5ba;

function toSansSerif(text: string): string {
  return [...text].map((ch) => {
    const c = ch.charCodeAt(0);
    if (c >= 65 && c <= 90)  return String.fromCodePoint(SANS_UP + c - 65);
    if (c >= 97 && c <= 122) return String.fromCodePoint(SANS_LO + c - 97);
    return ch;
  }).join("");
}

const SUPERSCRIPT: Record<string, string> = {
  A:"ᴬ",B:"ᴮ",C:"ᶜ",D:"ᴰ",E:"ᴱ",F:"ᶠ",G:"ᴳ",H:"ᴴ",I:"ᴵ",J:"ᴶ",
  K:"ᴷ",L:"ᴸ",M:"ᴹ",N:"ᴺ",O:"ᴼ",P:"ᴾ",Q:"Q",R:"ᴿ",S:"ˢ",T:"ᵀ",
  U:"ᵁ",V:"ⱽ",W:"ᵂ",X:"ˣ",Y:"ʸ",Z:"ᶻ",
};
function toSuperscript(text: string): string {
  return [...text].map((c) => SUPERSCRIPT[c.toUpperCase()] ?? c).join("");
}

const HEADER_LINE = "ㅤㅤㅤㅤㅤㅤ█▓▒▒░░░LINK TAXI👨‍🔬░░░▒▒▓██▓";
const DISCLAIMER  = "🛑 DISCLAIMER: ZERO TOLERANCE FOR SPAM, VÅBEN, NSFW ELLER EUFORISERENDE MIDLER!";

export function formatPost(links: Link[], subtitleTag = "ALTID OPDATERET!"): string {
  const subtitle = toSuperscript(subtitleTag);
  const header   = toSansSerif("GRUPPER DU KAN FORVENTE:");

  const body = links
    .map((l) => `${l.url}\n  - ${l.name} ${l.emoji}`)
    .join("\n");

  return [
    HEADER_LINE,
    `                                  ${subtitle}`,
    "",
    header,
    body,
    "",
    DISCLAIMER,
  ].join("\n");
}

export { toSansSerif, toSuperscript };
