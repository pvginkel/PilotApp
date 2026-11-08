/**
 * An attachment's address, under its document's, by its id (F28.5). The project's route opens it:
 * off a phone in a tab of its own, its document a link in its head; on a phone a view over the
 * document's, the link Back to it; this route draws nothing of its own.
 */

import { createFileRoute } from '@tanstack/react-router';

export const Route = createFileRoute('/_shell/projects/$address/documents/$documentId/attachments/$attachmentId')({});
