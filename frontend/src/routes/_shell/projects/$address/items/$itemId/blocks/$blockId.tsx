/**
 * A block's address, under its item's, by its id (F97). The project's route draws its timeline and
 * goes to the block, on a phone shows its item alone at the block (F99), and where the block's
 * document is a card, opens it at the block once it is read; this route draws nothing of its own.
 */

import { createFileRoute } from '@tanstack/react-router';
import { readBlock, readFirst } from '@/lib/screen-reads';

export const Route = createFileRoute('/_shell/projects/$address/items/$itemId/blocks/$blockId')({
  loader: readFirst(({ address, itemId }: { address: string; itemId: string; blockId: string }) => readBlock(address, itemId)),
});
