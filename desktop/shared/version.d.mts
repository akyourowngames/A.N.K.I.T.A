export declare const IPC_CONTRACT: number;

export type CompatCode = 'ok' | 'contract' | 'version';

export type Compat = {
  ok: boolean;
  code: CompatCode;
  detail: string;
  rendererVersion: string;
  mainVersion: string;
};

export type CompatIdentity = { version?: string | null; contract?: number | null };

export declare function checkCompat(main?: CompatIdentity, renderer?: CompatIdentity): Compat;
