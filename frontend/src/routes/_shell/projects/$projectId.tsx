/**
 * A project at its own address, by its id (F1.6). The browser remembers it as the current
 * project, which the bare address opens.
 */

import { useEffect } from 'react';
import { createFileRoute } from '@tanstack/react-router';
import { rememberInBrowser } from '@/lib/browser-state';

export const Route = createFileRoute('/_shell/projects/$projectId')({
  // Everything a project opens under its route starts closed on each project (F1.6).
  remountDeps: ({ params }) => params.projectId,
  component: Project,
});

function Project() {
  const { projectId } = Route.useParams();
  useEffect(() => rememberInBrowser({ project: projectId }), [projectId]);
  return null;
}
