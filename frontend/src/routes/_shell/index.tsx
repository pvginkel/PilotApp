/**
 * The bare address opens the project the browser remembers while it is in the list, else the
 * list's first (F1.6, F133); with no project, the centre says so (F113).
 */

import { createFileRoute, Navigate } from '@tanstack/react-router';
import { FolderKanban } from 'lucide-react';
import { EmptyState } from '@/components/shared/empty-state';
import { groupProjects, useProjectList } from '@/hooks/use-projects';
import { browserState } from '@/lib/browser-state';

export const Route = createFileRoute('/_shell/')({
  component: Home,
});

function Home() {
  const { data } = useProjectList();
  if (!data) return null;
  const { mine, others, finished } = groupProjects(data.projects);
  const listed = [...mine, ...others, ...finished];
  const project = listed.find((tab) => tab.id === browserState().project) ?? listed[0];
  if (!project) return <EmptyState icon={FolderKanban} title="No projects yet" testId="projects.empty" />;
  return <Navigate to="/projects/$projectId" params={{ projectId: project.id }} replace />;
}
