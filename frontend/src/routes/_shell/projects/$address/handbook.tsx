/**
 * The project's handbook's address, under its project's (F129.4). The project's route opens the
 * handbook: off a phone in its tab, on a phone a view over the timeline, once it is read; this route
 * draws nothing of its own.
 */

import { createFileRoute } from '@tanstack/react-router';
import { readFirst, readHandbook } from '@/lib/screen-reads';

export const Route = createFileRoute('/_shell/projects/$address/handbook')({
  loader: readFirst(({ address }: { address: string }) => readHandbook(address)),
});
