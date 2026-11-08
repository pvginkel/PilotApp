/**
 * A new project, the plus's (F46.1): its definition chat with nothing behind it on the server until
 * its first message makes the draft (`new-project.tsx`). No project is at the address: no slug
 * starts `draft-`, and a draft's name is `draft-<number>`.
 */

import { createFileRoute } from '@tanstack/react-router';
import { NewProject } from '@/components/projects/new-project';

export const Route = createFileRoute('/_shell/projects/draft-new')({
  component: NewProject,
});
