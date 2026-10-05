// SVG paths for the island header tabs and badges.
// Ported from Coucou's windows/src/views/icons.ts (MIT License, (c) Louis Raille):
// stand-ins for the SF Symbols used by the macOS island, drawn on a 24x24 grid.

export const ICONS = {
  house: 'M12 3.2 2.8 10.6V21h6.6v-5.4h5.2V21h6.6V10.6L12 3.2z',
  bubble: 'M12 3.6c-5 0-9 3.3-9 7.4 0 2.3 1.3 4.4 3.3 5.7-.2 1.2-.8 2.4-1.7 3.4 1.9-.2 3.6-.9 4.9-1.9 .8.2 1.6.3 2.5.3 5 0 9-3.3 9-7.5s-4-7.4-9-7.4z',
  plus: 'M11 4h2v7h7v2h-7v7h-2v-7H4v-2h7V4z',
  gear: 'M12 8.6a3.4 3.4 0 1 0 0 6.8 3.4 3.4 0 0 0 0-6.8zm0 1.8a1.6 1.6 0 1 1 0 3.2 1.6 1.6 0 0 1 0-3.2zM10.9 2h2.2l.35 2.1c.6.17 1.16.4 1.67.71l1.9-1 1.55 1.55-1 1.9c.3.5.54 1.07.7 1.67l2.13.35v2.2l-2.12.35c-.17.6-.4 1.16-.71 1.67l1 1.9-1.55 1.55-1.9-1c-.5.3-1.07.54-1.67.7L13.1 22h-2.2l-.35-2.12c-.6-.17-1.16-.4-1.67-.71l-1.9 1L5.43 18.6l1-1.9c-.3-.5-.54-1.07-.7-1.67L3.6 14.7v-2.2l2.12-.35c.17-.6.4-1.16.71-1.67l-1-1.9 1.55-1.55 1.9 1c.5-.3 1.07-.54 1.67-.7L10.9 2z',
  speakerOn: 'M11 4.5 6.5 8.2H3.4v7.6h3.1L11 19.5v-15zm3.2 3a5.3 5.3 0 0 1 0 9 .9.9 0 0 0 .9 1.55 7.1 7.1 0 0 0 0-12.1.9.9 0 0 0-.9 1.55zm2.6-3.1a8.9 8.9 0 0 1 0 15.2.9.9 0 0 0 .92 1.55 10.7 10.7 0 0 0 0-18.3.9.9 0 0 0-.92 1.55z',
  speakerOff: 'M11 4.5 6.5 8.2H3.4v7.6h3.1L11 19.5v-15zm3.6 4.1 1.27-1.27 2.33 2.33 2.33-2.33 1.27 1.27L19.47 11l2.33 2.33-1.27 1.27-2.33-2.33-2.33 2.33-1.27-1.27L16.93 11 14.6 8.6z',
  arrowUpRight: 'M8.5 7h8.5v8.5h-2V10.4l-7.1 7.1-1.4-1.4 7.1-7.1H8.5V7z',
  chevronRight: 'M9 5.5 15.5 12 9 18.5',
  check: 'M5 12.5 9.5 17 19 7.5',
  arrowUp: 'M12 4.5 5.5 11l1.5 1.5 4-4V19.5h2V8.5l4 4L18.5 11 12 4.5z',
  bang: 'M11 4h2v10h-2V4zm0 12.2h2v2.2h-2v-2.2z',
  xmark: 'M6.4 5 12 10.6 17.6 5 19 6.4 13.4 12 19 17.6 17.6 19 12 13.4 6.4 19 5 17.6 10.6 12 5 6.4 6.4 5z',
} as const;

export type IconName = keyof typeof ICONS;

export function Icon({ name, size = 14, stroke }: { name: IconName; size?: number; stroke?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" aria-hidden="true">
      <path
        d={ICONS[name]}
        fill={stroke ? 'none' : 'currentColor'}
        stroke={stroke ? 'currentColor' : undefined}
        strokeWidth={stroke ?? undefined}
        strokeLinecap={stroke ? 'round' : undefined}
        strokeLinejoin={stroke ? 'round' : undefined}
      />
    </svg>
  );
}
