/**
 * What closes what the overlay shows: on a phone Back, which takes its view off and shows what lay
 * under it (F98.5); off one a tab's close, which shows the tab that showed before it (F28.8), and
 * the session log's, going to the project's address in its entry's place (F97).
 */

import { useContext } from 'react';
import { useNavigate } from '@tanstack/react-router';
import { DocTabContext } from '@/hooks/use-doc-tabs';
import { PhoneViewContext } from '@/hooks/use-phone-tab';

export function useOverlayClose(projectId: string): () => void {
  const view = useContext(PhoneViewContext);
  const tab = useContext(DocTabContext);
  const navigate = useNavigate();
  return view?.back ?? tab?.close ?? (() => void navigate({ to: '/projects/$projectId', params: { projectId }, replace: true }));
}
