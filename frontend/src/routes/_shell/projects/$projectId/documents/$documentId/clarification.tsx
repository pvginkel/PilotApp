/**
 * A document's address at the box over its prose that holds Pilot's questions to its writer and the
 * reply (F52.2). The project's route opens the document and goes
 * to the box; this route draws nothing of its own.
 */

import { createFileRoute } from '@tanstack/react-router';

export const Route = createFileRoute('/_shell/projects/$projectId/documents/$documentId/clarification')({});
