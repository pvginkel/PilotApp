/**
 * An attachment's address, under its item's, by its id (F28.5). The project's route opens it in
 * the overlay over its timeline, as the item's attachment; this route draws nothing of its own.
 */

import { createFileRoute } from '@tanstack/react-router';

export const Route = createFileRoute('/_shell/projects/$projectId/items/$itemId/attachments/$attachmentId')({});
