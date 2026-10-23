/**
 * An attachment's address, under its document's, by its id (F28.5). The project's route shows it
 * in the document's overlay in the document's place, with an arrow back to the document; this
 * route draws nothing of its own.
 */

import { createFileRoute } from '@tanstack/react-router';

export const Route = createFileRoute('/_shell/projects/$projectId/documents/$documentId/attachments/$attachmentId')({});
