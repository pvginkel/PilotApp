/**
 * A done work item's debrief's address, under its session log's (F26.9). The project's route draws
 * its timeline and opens the debrief over it where the session log opens; this route draws nothing
 * of its own.
 */

import { createFileRoute } from '@tanstack/react-router';

export const Route = createFileRoute('/_shell/projects/$address/sessions/$sessionId/debrief')({});
