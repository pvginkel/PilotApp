/**
 * What closes what the overlay shows: on a phone Back, which takes its view off and shows what lay
 * under it (F98.5); off one, going to the project's address.
 */

import { useContext } from 'react';
import { useNavigate } from '@tanstack/react-router';
import { PhoneViewContext } from '@/hooks/use-phone-tab';

export function useOverlayClose(projectId: string): () => void {
  const view = useContext(PhoneViewContext);
  const navigate = useNavigate();
  return view?.back ?? (() => void navigate({ to: '/projects/$projectId', params: { projectId } }));
}
