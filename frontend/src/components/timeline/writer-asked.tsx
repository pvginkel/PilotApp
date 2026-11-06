/**
 * That Pilot asked a registered document's writer about a block (F52.2): Pilot's mark and "Pilot
 * asked the writer" in the block's head, or in the item's where the item's head is the block's (a
 * one-ask item's, a confirmation's). It is a button that opens the document at the box over its
 * prose holding the questions and the writer's reply (clarification.tsx), at the box's own address;
 * in the overlay showing the document, it goes to the box there.
 */

import { useContext } from 'react';
import { Link, useParams } from '@tanstack/react-router';
import { Avatar } from '@/components/shared/avatar';
import { ToClarificationContext } from '@/components/timeline/to-clarification';
import { useTabReplace } from '@/hooks/use-doc-tabs';

const TITLE = 'Show Pilot’s question to the writer and the reply';

export function WriterAsked({ documentId, testId }: { documentId: string; testId: string }) {
  const { projectId } = useParams({ from: '/_shell/projects/$projectId' });
  const replace = useTabReplace();
  const toBox = useContext(ToClarificationContext);
  const words = (
    <>
      <Avatar who="pilot" size="xs" />
      <span>Pilot asked the writer</span>
    </>
  );
  if (toBox !== null) {
    return (
      <button type="button" className="pilot-mark asked" onClick={toBox} title={TITLE} data-testid={testId}>
        {words}
      </button>
    );
  }
  return (
    <Link
      to="/projects/$projectId/documents/$documentId/clarification"
      params={{ projectId, documentId }}
      replace={replace}
      className="pilot-mark asked"
      title={TITLE}
      data-testid={testId}
    >
      {words}
    </Link>
  );
}
