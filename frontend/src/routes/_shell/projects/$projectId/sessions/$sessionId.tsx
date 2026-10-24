/**
 * A work item's session log's address, under its project's, by its session's id, which is the
 * item's (F69, F97). The project's route draws its timeline and opens the session log over it in
 * the overlay; this route draws nothing of its own.
 */

import { createFileRoute } from '@tanstack/react-router';

export const Route = createFileRoute('/_shell/projects/$projectId/sessions/$sessionId')({});
