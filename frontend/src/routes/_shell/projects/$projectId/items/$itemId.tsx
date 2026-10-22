/**
 * An item's address, under its project's, by its id (F97). The project's route draws its timeline
 * and goes to the item; this route draws nothing of its own.
 */

import { createFileRoute } from '@tanstack/react-router';

export const Route = createFileRoute('/_shell/projects/$projectId/items/$itemId')({});
