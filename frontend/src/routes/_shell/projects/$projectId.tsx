/**
 * A project at its own address, by its id (F1.6): its head over its timeline. The browser
 * remembers it as the current project, which the bare address opens.
 */

import { useEffect } from 'react';
import { createFileRoute } from '@tanstack/react-router';
import { ProjectHead } from '@/components/projects/project-head';
import { Timeline } from '@/components/timeline/timeline';
import { useProjectHead } from '@/hooks/use-projects';
import { rememberInBrowser } from '@/lib/browser-state';

export const Route = createFileRoute('/_shell/projects/$projectId')({
  // Everything a project opens under its route starts closed on each project, and its timeline
  // at its end (F1.6).
  remountDeps: ({ params }) => params.projectId,
  component: Project,
});

function Project() {
  const { projectId } = Route.useParams();
  useEffect(() => rememberInBrowser({ project: projectId }), [projectId]);
  const { data } = useProjectHead(projectId);
  return (
    <>
      {data && <ProjectHead project={data} />}
      <Timeline projectId={projectId} />
    </>
  );
}
