/**
 * The project document's address, `project.md`'s, under its project's (F37.4). The project's route
 * opens the document: off a phone in its tab, on a phone a view over the timeline, once it is read;
 * this route draws nothing of its own.
 */

import { createFileRoute } from '@tanstack/react-router';
import { readFirst, readProjectDocument } from '@/lib/screen-reads';

export const Route = createFileRoute('/_shell/projects/$address/project-document')({
  loader: readFirst(({ address }: { address: string }) => readProjectDocument(address)),
});
