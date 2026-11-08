/**
 * Going to what a quote names (F39.3), from wherever its chip stands in a project: an item to its
 * address, a block to its own, which opens its document where it is a card, an ask of
 * `project.md` to the project's route's place for it (use-draft-place.ts), and a path to its file —
 * the handbook, the project document, or an attachment at its address, under its
 * item's where it hangs on one, found in the timeline's read by its batch and file name. A path
 * naming no attachment of the read goes nowhere.
 */

import { useCallback } from 'react';
import { useNavigate } from '@tanstack/react-router';
import { useTabReplace } from '@/hooks/use-doc-tabs';
import { useToDraftBlock } from '@/hooks/use-draft-place';
import { useShownProject } from '@/hooks/use-project-address';
import { hungAt } from '@/hooks/use-timeline';
import { useGetProjectsTimelineByProjectId } from '@/lib/api/generated/hooks';
import type { QuoteRef } from '@/lib/chat/quotes';

const DRAFT_BLOCK = 'project.md/';

export function useOpenQuote(): (quote: QuoteRef) => void {
  const { id: projectId, address } = useShownProject();
  const navigate = useNavigate();
  const replace = useTabReplace();
  const toDraftBlock = useToDraftBlock();
  const { data } = useGetProjectsTimelineByProjectId({ path: { project_id: projectId } });
  return useCallback(
    ({ kind, id }: QuoteRef) => {
      if (kind === 'item') {
        void navigate({ to: '/projects/$address/items/$itemId', params: { address, itemId: id }, replace });
      } else if (kind === 'block' && id.startsWith(DRAFT_BLOCK)) {
        toDraftBlock(id.slice(DRAFT_BLOCK.length));
      } else if (kind === 'block') {
        const [itemId, blockId] = id.split('/');
        void navigate({ to: '/projects/$address/items/$itemId/blocks/$blockId', params: { address, itemId: itemId!, blockId: blockId! }, replace });
      } else if (id === 'handbook.md') {
        void navigate({ to: '/projects/$address/handbook', params: { address }, replace });
      } else if (id === 'project.md') {
        void navigate({ to: '/projects/$address/project-document', params: { address }, replace });
      } else {
        const hung = data === undefined ? undefined : hungAt(data, id);
        if (hung === undefined) return;
        const attachmentId = hung.attachment.id;
        void (hung.item === null
          ? navigate({ to: '/projects/$address/attachments/$attachmentId', params: { address, attachmentId }, replace })
          : navigate({
              to: '/projects/$address/items/$itemId/attachments/$attachmentId',
              params: { address, itemId: hung.item.id, attachmentId },
              replace,
            }));
      }
    },
    [address, data, navigate, replace, toDraftBlock],
  );
}
