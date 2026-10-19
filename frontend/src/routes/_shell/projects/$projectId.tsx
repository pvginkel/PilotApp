/**
 * A project at its own address, by its id (F1.6): its head above an empty body, the timeline's
 * place (005). The browser remembers it as the current project, which the bare address opens.
 */

import { useEffect } from 'react';
import { createFileRoute } from '@tanstack/react-router';
import { ProjectHead } from '@/components/projects/project-head';
import { useProjectHead } from '@/hooks/use-projects';
import { rememberInBrowser } from '@/lib/browser-state';

export const Route = createFileRoute('/_shell/projects/$projectId')({
  // Everything a project opens under its route starts closed on each project (F1.6).
  remountDeps: ({ params }) => params.projectId,
  component: Project,
});

function Project() {
  const { projectId } = Route.useParams();
  useEffect(() => rememberInBrowser({ project: projectId }), [projectId]);
  const { data } = useProjectHead(projectId);
  return data ? <ProjectHead project={data} /> : null;
}
