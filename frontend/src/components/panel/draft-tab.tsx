/**
 * A draft's Draft tab (F46.3): its `project.md` as Pilot writes it, read again on each of its
 * project's live events (F80.2): its title, then its prose and its asks in their order, each ask
 * answered in place (F47.4), then Pilot's dots while a turn saves it (F35), or, once none does, what
 * Create project does with it. Before its first save it reads "Empty" and what it is for (the
 * mockup's `renderDraft`). A link in it to a document Pilot attached opens that in the overlay;
 * nothing else in it links (F47.3). An ask an effect line or a quote goes to is scrolled into view
 * and flashed (use-draft-place.ts). A read that fails says so (F113).
 */

import { useEffect, useRef, type AnimationEvent } from 'react';
import { Link, useParams } from '@tanstack/react-router';
import { Markdown, type DocumentLinkProps } from '@/components/shared/markdown';
import { DraftBlock } from '@/components/timeline/block';
import { useFlashes } from '@/components/timeline/flash';
import { PilotWriting } from '@/components/timeline/writing';
import { useProjectDraft } from '@/hooks/use-document';
import { useDraftPlace } from '@/hooks/use-draft-place';
import { hungAt } from '@/hooks/use-timeline';
import { useGetProjectsTimelineByProjectId } from '@/lib/api/generated/hooks';

export function DraftTab({ projectId }: { projectId: string }) {
  const { data, error } = useProjectDraft(projectId, 'panel.draft');
  const { place, reached } = useDraftPlace(projectId);
  const { fresh, flashed, flash } = useFlashes();
  const sheet = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (place === null || data === undefined) return;
    // An ask the draft no longer holds is gone to nowhere.
    const block = sheet.current?.querySelector(`[data-block-id="${CSS.escape(place.block)}"]`);
    if (block) {
      block.scrollIntoView({ block: 'center' });
      flash(place.block);
    }
    reached(place);
  }, [place, data, flash, reached]);

  if (error !== null) {
    return (
      <p className="draft-empty" data-testid="panel.draft.failed">
        The draft did not load.
      </p>
    );
  }
  if (data === undefined) return null;
  if (data.title === null && data.body.length === 0) {
    return (
      <>
        <p className="draft-empty" data-testid="panel.draft.empty">
          Empty. Pilot writes the project here as you talk, and nothing is set up until you press <b>Create project</b>.
        </p>
        {data.writing && <PilotWriting />}
      </>
    );
  }
  return (
    <div ref={sheet} className="draft" data-testid="panel.draft">
      {data.title !== null && (
        <div className="prose">
          <h1 data-testid="panel.draft.title">{data.title}</h1>
        </div>
      )}
      {data.body.map((part, index) =>
        part.type === 'block' ? (
          <DraftBlock
            key={`block ${part.block.id}`}
            projectId={projectId}
            block={part.block}
            title={data.title}
            flash={{
              flashing: fresh.has(part.block.id),
              onAnimationEnd: (event: AnimationEvent) => {
                if (event.target === event.currentTarget) flashed(part.block.id);
              },
            }}
          />
        ) : (
          <Markdown key={`prose ${index}`} text={part.markdown} documentLink={DraftLink} />
        ),
      )}
      {data.writing ? (
        <PilotWriting />
      ) : (
        <p className="draft-foot" data-testid="panel.draft.foot">
          Change anything in the chat. <b>Create project</b> hands it to Pilot, which sets it up and starts the plan.
        </p>
      )}
    </div>
  );
}

/** A link of the draft: to an attachment by its path in the project's folder, in the overlay; any other its words alone. */
function DraftLink({ href, children }: DocumentLinkProps) {
  const { projectId } = useParams({ from: '/_shell/projects/$projectId' });
  const { data } = useGetProjectsTimelineByProjectId({ path: { project_id: projectId } });
  const hung = data === undefined ? undefined : hungAt(data, pathOf(href));
  if (hung === undefined) return <>{children}</>;
  return (
    <Link
      to="/projects/$projectId/attachments/$attachmentId"
      params={{ projectId, attachmentId: hung.attachment.id }}
      data-testid="panel.draft.link"
    >
      {children}
    </Link>
  );
}

/** The path a link names in the project's folder: as written, less a leading `./`, its escapes decoded. */
function pathOf(href: string): string {
  const path = href.replace(/^\.\//, '');
  try {
    return decodeURI(path);
  } catch {
    // An escape of no UTF-8: the path as written, which names no file.
    return path;
  }
}
