/** The keys list (F110), which `?` opens: Pilot's own keys. */

import { Dialog } from '@/components/shared/dialog';

export function KeysList({ onClose }: { onClose: () => void }) {
  return (
    <Dialog layer="keys" title="Keys" onClose={onClose} testId="shell.keys">
      <dl className="keys">
        <dt>
          <kbd>Esc</kbd>
        </dt>
        <dd>close what is on top, one per press</dd>
        <dt>
          <kbd>?</kbd>
        </dt>
        <dd>this list</dd>
      </dl>
    </Dialog>
  );
}
