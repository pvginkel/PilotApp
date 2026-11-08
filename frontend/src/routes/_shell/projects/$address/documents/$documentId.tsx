/**
 * A document's address, under its project's, by its item's id (F97). The project's route opens the
 * document: off a phone in its tab, on a phone a view over the timeline, once the document is read;
 * this route draws nothing of its own.
 */

import { createFileRoute } from '@tanstack/react-router';
import { readDocument, readFirst } from '@/lib/screen-reads';

export const Route = createFileRoute('/_shell/projects/$address/documents/$documentId')({
  loader: readFirst(({ documentId }: { address: string; documentId: string }) => readDocument(documentId)),
});
