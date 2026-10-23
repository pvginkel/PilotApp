/**
 * An attachment's bytes as text, read from its stream, GET /api/attachments/<id> (F28.5), which
 * serves Markdown and every other text but HTML as `text/plain`, and an SVG as a download.
 */

import { useQuery } from '@tanstack/react-query';
import { toApiError } from '@/lib/api/api-error';
import { api } from '@/lib/api/client';
import { useUiStateInstrumentation } from '@/lib/test/ui-state';

/** The attachment's stream. */
export const attachmentUrl = (id: string) => `/api/attachments/${id}`;

export function useAttachmentText(id: string) {
  const query = useQuery({
    queryKey: ['getAttachmentsByAttachmentId', 'text', id],
    queryFn: async () => {
      const result = await api.GET('/api/attachments/{attachment_id}', { params: { path: { attachment_id: id } }, parseAs: 'text' });
      if (result.error) throw toApiError(result.error, result.response.status);
      // openapi-fetch answers an empty body with `{}`.
      return typeof result.data === 'string' ? result.data : '';
    },
  });
  useUiStateInstrumentation('overlay.attachment', { isLoading: query.isLoading, error: query.error });
  return query;
}
