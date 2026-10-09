export type BrowserNotice = { kind: 'reference' | 'navigation' | 'connection' | 'setup' | 'preview' | 'action' | 'denied' | 'login'; message: string };
export declare function browserNotice(error: unknown, fallback?: BrowserNotice['kind']): BrowserNotice;
export declare function browserNeedsConnection(notice: BrowserNotice | null | undefined): boolean;
export declare function browserPageFailed(notice: BrowserNotice | null | undefined): boolean;
export declare function browserNoticeIsRecoverable(notice: BrowserNotice | null | undefined): boolean;
