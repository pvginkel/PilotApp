/**
 * The project's journal's address, under its project's (F169.4). The project's route opens the
 * journal: off a phone in its tab, on a phone a view over the timeline, once it is read; this route
 * draws nothing of its own.
 */

import { createFileRoute } from '@tanstack/react-router';
import { readFirst, readJournal } from '@/lib/screen-reads';

export const Route = createFileRoute('/_shell/projects/$address/journal')({
  loader: readFirst(({ address }: { address: string }) => readJournal(address)),
});
