/** WCAG 2.x relative luminance / contrast ratio. Colors as #rrggbb or #rrggbbaa (alpha composited on `under`). */
export function parseHex(hex: string): [number, number, number, number] {
  const h = hex.replace("#", "");
  const n = (i: number) => parseInt(h.slice(i, i + 2), 16);
  return [n(0), n(2), n(4), h.length >= 8 ? n(6) / 255 : 1];
}

export function composite(fg: string, under: string): [number, number, number] {
  const [r, g, b, a] = parseHex(fg);
  const [R, G, B] = parseHex(under);
  return [r * a + R * (1 - a), g * a + G * (1 - a), b * a + B * (1 - a)];
}

function lum([r, g, b]: [number, number, number]): number {
  const c = (v: number) => {
    const s = v / 255;
    return s <= 0.03928 ? s / 12.92 : ((s + 0.055) / 1.055) ** 2.4;
  };
  return 0.2126 * c(r) + 0.7152 * c(g) + 0.0722 * c(b);
}

/** Contrast of `fg` text on `bg` (bg may be a translucent tint over `surface`). */
export function contrast(fg: string, bg: string, surface = bg): number {
  const b = composite(bg, surface);
  const f = composite(fg, `#${b.map((v) => Math.round(v).toString(16).padStart(2, "0")).join("")}`);
  const [l1, l2] = [lum(f), lum(b)].sort((x, y) => y - x);
  return (l1 + 0.05) / (l2 + 0.05);
}
