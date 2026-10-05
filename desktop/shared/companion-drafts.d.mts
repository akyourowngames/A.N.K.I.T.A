export type DraftAttachment = {name: string; image: boolean; data: string; preview?: string; kind?: 'document'; images?: string[]};
export type CompanionDraft = {text: string; files: DraftAttachment[]; error: string; reading: boolean};
export const EMPTY_COMPANION_DRAFT: CompanionDraft;
export class CompanionDrafts {
  subscribe(listener: () => void): () => void;
  getSnapshot(): Record<string, CompanionDraft>;
  get(id: string): CompanionDraft;
  hasReceipt(id: string): boolean;
  update(id: string, updater: (draft: CompanionDraft) => CompanionDraft): void;
  capture(item: {id: string; threadId: string; attachment: DraftAttachment}): boolean;
  read(id: string, files: File[], reader: (file: File) => Promise<DraftAttachment>): Promise<{accepted: number; error: string}>;
}
