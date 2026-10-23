export function parseColorCode(input: string): string | null {
  const value = input.trim();
  const hex = /^#?([\da-f]{6})$/i.exec(value);
  if (hex) return `#${hex[1].toLowerCase()}`;

  const rgb = /^rgb\(\s*(\d{1,3})\s*,\s*(\d{1,3})\s*,\s*(\d{1,3})\s*\)$/i.exec(value)
    ?? /^(\d{1,3})\s*,\s*(\d{1,3})\s*,\s*(\d{1,3})$/.exec(value);
  if (!rgb) return null;
  const channels = rgb.slice(1).map(Number);
  if (channels.some((channel) => channel > 255)) return null;
  return `#${channels.map((channel) => channel.toString(16).padStart(2, "0")).join("")}`;
}

export function colorToRgb(color: string): string {
  const parsed = parseColorCode(color);
  if (!parsed) return color;
  const channels = [0, 2, 4].map((offset) => Number.parseInt(parsed.slice(offset + 1, offset + 3), 16));
  return `rgb(${channels.join(", ")})`;
}
