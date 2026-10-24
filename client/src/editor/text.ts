export const MAX_TEXT_CODE_POINTS = 10_000;
export const TEXT_LENGTH_ERROR_MESSAGE = "Text is over the 10,000-character limit. Shorten it to save; your full draft is preserved.";

export function isTextWithinLimit(text: string): boolean {
  const codePoints = text[Symbol.iterator]();
  for (let length = 0; length <= MAX_TEXT_CODE_POINTS; length += 1) {
    if (codePoints.next().done) return true;
  }
  return false;
}
