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
import { useShownProject } from '@/hooks/use-project-address';

export function useOverlayClose(): () => void {
  const { id: projectId, address } = useShownProject();
  const view = useContext(PhoneViewContext);
  const tab = useContext(DocTabContext);
  const navigate = useNavigate();
  const closePopover = () => {
    const under = tabLeftOn(projectId);
    void (under === null
      ? navigate({ to: '/projects/$address', params: { address }, replace: true })
      : navigate({ href: under.href, replace: true }));
  };
  return view?.back ?? tab?.close ?? closePopover;
}
