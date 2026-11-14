/**
 * The Debrief (F26.6): an icon button, its name its tooltip, on a done work item whose stage
 * session gave a debrief, opening the debrief at its address under the session log's, where the
 * session log opens (F26.9).
 */

import { Link } from '@tanstack/react-router';
import { NotebookPen } from 'lucide-react';
import { useTabReplace } from '@/hooks/use-doc-tabs';
import { useShownProject } from '@/hooks/use-project-address';

export function DebriefButton({ itemId, testId }: { itemId: string; testId: string }) {
  const { address } = useShownProject();
  const replace = useTabReplace();
  return (
    <Link
      to="/projects/$address/sessions/$sessionId/debrief"
      params={{ address, sessionId: itemId }}
      replace={replace}
      className="btn btn-ghost btn-sm btn-icon"
      title="Debrief"
      aria-label="Debrief"
      data-testid={testId}
    >
      <NotebookPen className="icon" aria-hidden="true" />
    </Link>
  );
}
