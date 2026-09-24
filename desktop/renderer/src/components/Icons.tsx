import type { ReactNode } from 'react';

export function Icon({ name, size = 18, stroke = 1.8 }: { name: string; size?: number; stroke?: number }) {
  const shared = { width: size, height: size, viewBox: '0 0 24 24', fill: 'none', stroke: 'currentColor', strokeWidth: stroke, strokeLinecap: 'round' as const, strokeLinejoin: 'round' as const, 'aria-hidden': true as const };
  const paths: Record<string, ReactNode> = {
    plus: <path d="M12 5v14M5 12h14" />,
    search: <><circle cx="11" cy="11" r="6.5"/><path d="m16 16 4 4"/></>,
    send: <path d="M12 19V5m-6 6 6-6 6 6" />,
    stop: <rect x="6.5" y="6.5" width="11" height="11" rx="2" fill="currentColor" stroke="none" />,
    chevron: <path d="m7 10 5 5 5-5" />,
    more: <><circle cx="5" cy="12" r="1" fill="currentColor"/><circle cx="12" cy="12" r="1" fill="currentColor"/><circle cx="19" cy="12" r="1" fill="currentColor"/></>,
    close: <path d="M6 6l12 12M18 6 6 18" />,
    panel: <><rect x="3" y="4" width="18" height="16" rx="3"/><path d="M9 4v16"/></>,
    sparkle: <><path d="m12 2 2.3 7.7L22 12l-7.7 2.3L12 22l-2.3-7.7L2 12l7.7-2.3L12 2Z"/></>,
    edit: <><path d="m4 20 4.5-.8L19 8.7 15.3 5 4.8 15.5 4 20Z"/><path d="m13.7 6.6 3.7 3.7"/></>,
    trash: <><path d="M4 7h16M10 4h4M7 7l1 13h8l1-13M10 11v5M14 11v5"/></>,
    external: <><path d="M13 4h7v7M20 4l-9 9"/><path d="M20 14v5a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V5a1 1 0 0 1 1-1h5"/></>,
    check: <path d="m5 12 4 4L19 6" />,
    alert: <><circle cx="12" cy="12" r="9"/><path d="M12 7v6M12 17h.01"/></>,
    copy: <><rect x="9" y="9" width="11" height="11" rx="2.5"/><path d="M5 15V6a2 2 0 0 1 2-2h9"/></>,
    panelLeft: <><rect x="3" y="4" width="18" height="16" rx="3"/><path d="M9 4v16"/></>,
    settings: <><path d="M10 2.8h4l.6 2.2 1.7.7 2-.9 2.8 2.8-.9 2 .7 1.7 2.2.6v4l-2.2.6-.7 1.7.9 2-2.8 2.8-2-.9-1.7.7-.6 2.2h-4l-.6-2.2-1.7-.7-2 .9-2.8-2.8.9-2-.7-1.7-2.2-.6v-4l2.2-.6.7-1.7-.9-2 2.8-2.8 2 .9 1.7-.7.6-2.2Z"/><circle cx="12" cy="12" r="3"/></>,
    cube: <><path d="m12 2 9 5-9 5-9-5 9-5ZM3 7v10l9 5 9-5V7M12 12v10"/></>,
    palette: <><path d="M12 3a9 9 0 0 0 0 18h1.5a2 2 0 0 0 1.5-3.3 1.6 1.6 0 0 1 1.2-2.7H18a3 3 0 0 0 3-3 9 9 0 0 0-9-9Z"/><circle cx="7.5" cy="11" r=".7" fill="currentColor"/><circle cx="10" cy="7" r=".7" fill="currentColor"/><circle cx="15" cy="7" r=".7" fill="currentColor"/></>,
    info: <><circle cx="12" cy="12" r="9"/><path d="M12 11v6M12 7h.01"/></>,
    key: <><circle cx="7.5" cy="15.5" r="4.5"/><path d="m11 12 9-9 2 2-2 2 1 2-2 2-2-1-2 2"/></>,
    eye: <><path d="M2 12s3.5-6 10-6 10 6 10 6-3.5 6-10 6S2 12 2 12Z"/><circle cx="12" cy="12" r="2.5"/></>,
    eyeOff: <><path d="M3 3 21 21M10.6 6.1A12 12 0 0 1 12 6c6.5 0 10 6 10 6a15 15 0 0 1-3.5 3.8M6.2 7.9C3.5 9.5 2 12 2 12s3.5 6 10 6c1.5 0 2.8-.3 4-.8"/><path d="M10 10a2.5 2.5 0 0 0 4 4"/></>,
    plug: <><path d="M8 3v5M16 3v5M6 8h12v4a6 6 0 0 1-5 5.9V21h-2v-3.1A6 6 0 0 1 6 12V8Z"/></>,
    refresh: <><path d="M20 7v5h-5M4 17v-5h5"/><path d="M5.7 9A7 7 0 0 1 18 7l2 5M4 12l2 5a7 7 0 0 0 12.3-2"/></>,
    arrowRight: <path d="M4 12h16m-6-6 6 6-6 6" />,
    folder: <path d="M3 7a2 2 0 0 1 2-2h5l2 2h7a2 2 0 0 1 2 2v10H3V7Z" />,
    file: <><path d="M6 2h8l5 5v15H6a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2Z"/><path d="M14 2v6h5M8 13h8M8 17h6"/></>,
    code: <><path d="m8 7-5 5 5 5m8-10 5 5-5 5M14 4l-4 16"/></>,
    broadcast: <><circle cx="12" cy="12" r="2"/><path d="M8.6 8.6a4.8 4.8 0 0 0 0 6.8M15.4 8.6a4.8 4.8 0 0 1 0 6.8M5.8 5.8a8.8 8.8 0 0 0 0 12.4M18.2 5.8a8.8 8.8 0 0 1 0 12.4"/></>,
    user: <><circle cx="12" cy="8" r="4"/><path d="M4 21c1.4-3.8 4.7-5.5 8-5.5s6.6 1.7 8 5.5"/></>,
  };
  return <svg {...shared}>{paths[name] || paths.sparkle}</svg>;
}
