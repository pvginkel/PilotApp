/**
 * An attachment's address, under its item's, by its id (F28.5). The project's route opens it as
 * the item's attachment: off a phone in a tab of its own, on a phone a view over the timeline; this
 * route draws nothing of its own.
 */

import { createFileRoute } from '@tanstack/react-router';

export const Route = createFileRoute('/_shell/projects/$address/items/$itemId/attachments/$attachmentId')({});
