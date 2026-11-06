/**
 * What closes what the overlay shows: on a phone Back, which takes its view off and shows what lay
 * under it (F98.5); off one a tab's close, which shows the tab that showed before it (F28.8), and
 * the session log's popover's, going to the address of the tab under it in its entry's place
 * (F97).
 */

import { useContext } from 'react';
import { useNavigate } from '@tanstack/react-router';
import { DocTabContext, tabLeftOn } from '@/hooks/use-doc-tabs';
import { PhoneViewContext } from '@/hooks/use-phone-tab';

export function useOverlayClose(projectId: string): () => void {
  const view = useContext(PhoneViewContext);
  const tab = useContext(DocTabContext);
  const navigate = useNavigate();
  const closePopover = () => {
    const under = tabLeftOn(projectId);
    void (under === null
      ? navigate({ to: '/projects/$projectId', params: { projectId }, replace: true })
      : navigate({ href: under.href, replace: true }));
  };
  return view?.back ?? tab?.close ?? closePopover;
}
