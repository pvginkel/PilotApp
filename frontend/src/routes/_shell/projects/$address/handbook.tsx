/**
 * The project's handbook's address, under its project's (F129.4). The project's route opens the
 * handbook: off a phone in its tab, on a phone a view over the timeline; this route draws nothing of
 * its own.
 */

import { createFileRoute } from '@tanstack/react-router';

export const Route = createFileRoute('/_shell/projects/$address/handbook')({});
