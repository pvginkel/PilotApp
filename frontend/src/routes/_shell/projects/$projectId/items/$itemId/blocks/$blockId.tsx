/**
 * A block's address, under its item's, by its id (F97). The project's route draws its timeline
 * and goes to the block; this route draws nothing of its own.
 */

import { createFileRoute } from '@tanstack/react-router';

export const Route = createFileRoute('/_shell/projects/$projectId/items/$itemId/blocks/$blockId')({});
