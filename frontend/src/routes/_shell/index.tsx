/**
 * The bare address: on a phone the home (F98.6), the first entry under every project it opens;
 * off one the project the browser remembers while it is in the list, else the list's first (F1.6,
 * F133), its hash kept, so that a dashboard's address stays one (F160.3), and with no project the
 * centre says so (F113).
 */

import { createFileRoute, Navigate, useRouterState } from '@tanstack/react-router';
import { FolderKanban } from 'lucide-react';
import { PhoneHome } from '@/components/projects/phone-home';
import { EmptyState } from '@/components/shared/empty-state';
import { usePhone } from '@/hooks/use-phone';
import { groupProjects, useProjectList } from '@/hooks/use-projects';
import { browserState } from '@/lib/browser-state';
import { hashOf } from '@/lib/screens';

export const Route = createFileRoute('/_shell/')({
  component: Home,
});

function Home() {
  return usePhone() ? <PhoneHome /> : <DeskHome />;
}

function DeskHome() {
  const { data } = useProjectList();
  const hash = useRouterState({ select: (state) => hashOf(state.location.href) });
  if (!data) return null;
  const { mine, others, finished } = groupProjects(data.projects);
  const listed = [...mine, ...others, ...finished];
  const project = listed.find((tab) => tab.id === browserState().project) ?? listed[0];
  if (!project) return <EmptyState icon={FolderKanban} title="No projects yet" testId="projects.empty" />;
  // As the browser holds it: the router's own hash is decoded, which would change what it says.
  return <Navigate to="/projects/$address" params={{ address: project.address }} hash={hash.slice(1)} replace />;
}
