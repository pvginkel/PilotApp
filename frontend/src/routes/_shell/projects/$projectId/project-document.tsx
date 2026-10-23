/**
 * The project document's address, `project.md`'s, under its project's (F37.4). The project's route
 * draws its timeline and opens the document over it in the overlay; this route draws nothing of
 * its own.
 */

import { createFileRoute } from '@tanstack/react-router';

export const Route = createFileRoute('/_shell/projects/$projectId/project-document')({});
