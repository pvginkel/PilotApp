/**
 * The project's handbook's address, under its project's (F129.4). The project's route draws its
 * timeline and opens the handbook over it in the overlay; this route draws nothing of its own.
 */

import { createFileRoute } from '@tanstack/react-router';

export const Route = createFileRoute('/_shell/projects/$projectId/handbook')({});
