import { useState } from 'react';
import type { EditedFile } from '../lib/activity';
import { Icon } from './Icons';

const PREVIEW_FILES = 3; // Files shown before the summary folds the rest behind "Show more".

export function EditSummaryCard({ files, onReview }: { files: EditedFile[]; onReview?: () => void }) {
  const [expanded, setExpanded] = useState(false);
  const shown = expanded ? files : files.slice(0, PREVIEW_FILES);
  const hidden = files.length - shown.length;
  const added = files.reduce((sum, file) => sum + file.added, 0);
  const removed = files.reduce((sum, file) => sum + file.removed, 0);
  return <div className="edit-summary">
    <div className="edit-summary-head">
      <span className="edit-summary-glyph"><Icon name="edit" size={15} /></span>
      <div className="edit-summary-heading">
        <strong>Edited {files.length} file{files.length === 1 ? '' : 's'}</strong>
        {(added > 0 || removed > 0) && <span className="edit-summary-stats"><b>+{added}</b> <i>-{removed}</i></span>}
      </div>
      {onReview && <button type="button" className="edit-summary-review" onClick={onReview}>Review <Icon name="arrowRight" size={13} /></button>}
    </div>
    <ul className="edit-summary-files">
      {shown.map(file => <li key={file.path}>
        <span className="edit-summary-path" title={file.path}>{file.path}</span>
        <span className="edit-summary-file-stats"><b>+{file.added}</b> <i>-{file.removed}</i></span>
      </li>)}
    </ul>
    {hidden > 0 && <button type="button" className="edit-summary-more" onClick={() => setExpanded(true)}>
      Show {hidden} more file{hidden === 1 ? '' : 's'} <Icon name="chevron" size={13} />
    </button>}
  </div>;
}
