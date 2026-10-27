/**
 * An attachment's address under its project's, by its id: a draft's material, hung on nothing
 * until Create project (F36.6). The project's route opens it in the overlay, wherever it hangs;
 * this route draws nothing of its own.
 */

import { createFileRoute } from '@tanstack/react-router';

export const Route = createFileRoute('/_shell/projects/$projectId/attachments/$attachmentId')({});
