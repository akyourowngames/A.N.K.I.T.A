export type BrowserNotice = { kind: 'reference' | 'navigation' | 'connection' | 'setup' | 'preview' | 'action'; message: string };
export declare function browserNotice(error: unknown, fallback?: BrowserNotice['kind']): BrowserNotice;
export declare function browserNeedsConnection(notice: BrowserNotice | null | undefined): boolean;
