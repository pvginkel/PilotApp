/**
 * Going to what a quote names (F39.3), from wherever its chip stands in a project: an item to its
 * address, a block to its own, which opens the overlay where its document is a card, an ask of
 * `project.md` to the project's route's place for it (use-draft-place.ts), and a path to its file's
 * overlay — the handbook's, the project document's, or an attachment's at its address, under its
 * item's where it hangs on one, found in the timeline's read by its batch and file name. A path
 * naming no attachment of the read goes nowhere.
 */

import { useCallback } from 'react';
import { useNavigate, useParams } from '@tanstack/react-router';
import { useToDraftBlock } from '@/hooks/use-draft-place';
import { hungAt } from '@/hooks/use-timeline';
import { useGetProjectsTimelineByProjectId } from '@/lib/api/generated/hooks';
import type { QuoteRef } from '@/lib/chat/quotes';

const DRAFT_BLOCK = 'project.md/';

export function useOpenQuote(): (quote: QuoteRef) => void {
  const { projectId } = useParams({ from: '/_shell/projects/$projectId' });
  const navigate = useNavigate();
  const toDraftBlock = useToDraftBlock();
  const { data } = useGetProjectsTimelineByProjectId({ path: { project_id: projectId } });
  return useCallback(
    ({ kind, id }: QuoteRef) => {
      if (kind === 'item') {
        void navigate({ to: '/projects/$projectId/items/$itemId', params: { projectId, itemId: id } });
      } else if (kind === 'block' && id.startsWith(DRAFT_BLOCK)) {
        toDraftBlock(id.slice(DRAFT_BLOCK.length));
      } else if (kind === 'block') {
        const [itemId, blockId] = id.split('/');
        void navigate({ to: '/projects/$projectId/items/$itemId/blocks/$blockId', params: { projectId, itemId: itemId!, blockId: blockId! } });
      } else if (id === 'handbook.md') {
        void navigate({ to: '/projects/$projectId/handbook', params: { projectId } });
      } else if (id === 'project.md') {
        void navigate({ to: '/projects/$projectId/project-document', params: { projectId } });
      } else {
        const hung = data === undefined ? undefined : hungAt(data, id);
        if (hung === undefined) return;
        const attachmentId = hung.attachment.id;
        void (hung.item === null
          ? navigate({ to: '/projects/$projectId/attachments/$attachmentId', params: { projectId, attachmentId } })
          : navigate({
              to: '/projects/$projectId/items/$itemId/attachments/$attachmentId',
              params: { projectId, itemId: hung.item.id, attachmentId },
            }));
      }
    },
    [data, navigate, projectId, toDraftBlock],
  );
}
