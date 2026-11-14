/**
 * A done work item's full debrief's address, under its debrief's (F26.10). The project's route
 * draws its timeline and opens the full debrief over it in the debrief's place; this route draws
 * nothing of its own.
 */

import { createFileRoute } from '@tanstack/react-router';

export const Route = createFileRoute('/_shell/projects/$address/sessions/$sessionId/debrief/full')({});
