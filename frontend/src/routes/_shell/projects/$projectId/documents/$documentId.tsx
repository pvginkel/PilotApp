/**
 * A document's address, under its project's, by its item's id (F97). The project's route draws its
 * timeline and opens the document over it in the overlay; this route draws nothing of its own.
 */

import { createFileRoute } from '@tanstack/react-router';

export const Route = createFileRoute('/_shell/projects/$projectId/documents/$documentId')({});
