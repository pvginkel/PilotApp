/**
 * The project's handbook (F129.4) and its project document, `project.md` (F37.4), in the overlay,
 * each at its own address over the project's timeline, opening as an attachment opens: rendered,
 * read only, no foot. Its head is its title over the project and what it is, and Discuss, quoting
 * it by its path in the project's folder (F39.1); its body its prose and its asks in their order,
 * each ask read only (D1), then Pilot's dots while a turn saves it (F35), or *Empty* while it has
 * no text past its title, as the handbook is born (F129.2). A link in its prose to the project's
 * attached material, by its path in the project's folder, opens the attachment where it hangs, the
 * draft's material on the opening after Create (F29.3, F18.1): off a phone in a tab of its own, on a
 * phone a view pushed over this one; one naming no attachment is its words alone, and any other
 * link opens in a new browser tab. A read that fails, a draft's handbook included, reads "The
 * document did not load" (F113).
 */

import { Link, useParams } from '@tanstack/react-router';
import { FileText, NotebookText, type LucideIcon } from 'lucide-react';
import { DiscussButton } from '@/components/chat/discuss-button';
import { quoteOfFile } from '@/components/chat/discuss-quotes';
import { DidNotLoad, Overlay } from '@/components/overlay/overlay';
import { LinkedText } from '@/components/shared/linked-text';
import { Markdown, type DocumentLinkProps } from '@/components/shared/markdown';
import { DocumentBlock } from '@/components/timeline/block';
import { PilotWriting } from '@/components/timeline/writing';
import { useTabReplace } from '@/hooks/use-doc-tabs';
import { useHandbook, useProjectDraft, type ProjectDocument } from '@/hooks/use-document';
import { useOverlayClose } from '@/hooks/use-overlay-close';
import type { ProjectHead } from '@/hooks/use-projects';
import { hungAt, pathOfLink } from '@/hooks/use-timeline';
import { useGetProjectsTimelineByProjectId } from '@/lib/api/generated/hooks';

interface ProjectDocumentOverlayProps {
  projectId: string;
  /** The project's head, once read. */
  project: ProjectHead | undefined;
}

export function HandbookOverlay({ projectId, project }: ProjectDocumentOverlayProps) {
  const read = useHandbook(projectId);
  return (
    <ReadOnlyOverlay
      projectId={projectId}
      project={project}
      read={read}
      showing="handbook"
      path="handbook.md"
      role="Handbook"
      icon={NotebookText}
    />
  );
}

export function ProjectDocumentOverlay({ projectId, project }: ProjectDocumentOverlayProps) {
  const read = useProjectDraft(projectId, 'overlay.draft');
  return (
    <ReadOnlyOverlay
      projectId={projectId}
      project={project}
      read={read}
      showing="project-document"
      path="project.md"
      role="Project document"
      icon={FileText}
    />
  );
}

interface ReadOnlyOverlayProps extends ProjectDocumentOverlayProps {
  read: { data: ProjectDocument | undefined; error: unknown };
  showing: string;
  /** Its path in the project's folder. */
  path: 'handbook.md' | 'project.md';
  /** What it is, which titles it where its text gives no title. */
  role: string;
  icon: LucideIcon;
}

function ReadOnlyOverlay({ projectId, project, read: { data, error }, showing, path, role, icon: Icon }: ReadOnlyOverlayProps) {
  const close = useOverlayClose(projectId);
  const failed = error !== null;
  const title = data?.title ?? role;
  return (
    <Overlay
      showing={showing}
      titles={
        !failed &&
        data && (
          <>
            <h2 title={title} data-testid="overlay.title">
              <Icon className="icon" aria-hidden="true" /> <LinkedText text={title} />
            </h2>
            <div className="sub" data-testid="overlay.sub">
              {project && (
                <>
                  <span data-testid="overlay.project">
                    <LinkedText text={project.name ?? 'New project'} />
                  </span>
                  <span>·</span>
                </>
              )}
              <span data-testid="overlay.role">{role}</span>
            </div>
          </>
        )
      }
      acts={!failed && data && <DiscussButton quote={quoteOfFile(path, title)} testId="overlay.discuss" />}
      foot={null}
      onClose={close}
    >
      {failed ? <DidNotLoad /> : data && <Body document={data} documentKey={`${projectId}/${path}`} />}
    </Overlay>
  );
}

/** `documentKey` keys its blocks, `<project>/<path>`. */
function Body({ document, documentKey }: { document: ProjectDocument; documentKey: string }) {
  return (
    <>
      {document.body.length === 0 ? (
        <p className="item-sub" data-testid="overlay.empty">
          Empty
        </p>
      ) : (
        <div className="sheet-doc" data-testid="overlay.document">
          {document.body.map((part, index) =>
            part.type === 'block' ? (
              <DocumentBlock key={`block ${part.block.id}`} document={documentKey} block={part.block} />
            ) : (
              <Markdown key={`prose ${index}`} text={part.markdown} materialLink={MaterialLink} />
            ),
          )}
        </div>
      )}
      {document.writing && <PilotWriting />}
    </>
  );
}

/** A link to the project's attached material: the attachment where it hangs, at its address under its item's or, hung on nothing, the project's. */
function MaterialLink({ href, children }: DocumentLinkProps) {
  const { projectId } = useParams({ from: '/_shell/projects/$projectId' });
  const { data } = useGetProjectsTimelineByProjectId({ path: { project_id: projectId } });
  const replace = useTabReplace();
  const hung = data === undefined ? undefined : hungAt(data, pathOfLink(href));
  if (hung === undefined) return <>{children}</>;
  const attachmentId = hung.attachment.id;
  return hung.item === null ? (
    <Link
      to="/projects/$projectId/attachments/$attachmentId"
      params={{ projectId, attachmentId }}
      replace={replace}
      data-testid="overlay.material-link"
    >
      {children}
    </Link>
  ) : (
    <Link
      to="/projects/$projectId/items/$itemId/attachments/$attachmentId"
      params={{ projectId, itemId: hung.item.id, attachmentId }}
      replace={replace}
      data-testid="overlay.material-link"
    >
      {children}
    </Link>
  );
}
