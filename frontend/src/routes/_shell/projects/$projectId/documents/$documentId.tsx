/**
 * A document's address, under its project's, by its item's id (F97), and with `block` the address
 * that opens it at that block, as a card's segment does (F33). The project's route draws its
 * timeline and opens the document over it in the overlay; this route draws nothing of its own.
 */

import { createFileRoute } from '@tanstack/react-router';

interface DocumentSearch {
  block?: string;
}

export const Route = createFileRoute('/_shell/projects/$projectId/documents/$documentId')({
  validateSearch: (search: Record<string, unknown>): DocumentSearch =>
    typeof search.block === 'string' ? { block: search.block } : {},
});
