/**
 * A document's address, under its project's, by its item's id (F97). The project's route opens the
 * document: off a phone in its tab, on a phone a view over the timeline; this route draws nothing
 * of its own.
 */

import { createFileRoute } from '@tanstack/react-router';

export const Route = createFileRoute('/_shell/projects/$projectId/documents/$documentId')({});
