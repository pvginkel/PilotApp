/**
 * The project's handbook (F129.4) and its project document, `project.md` (F37.4), in the overlay,
 * each at its own address over the project's timeline, opening as an attachment opens: rendered,
 * read only, no foot. Its head is its title over the project and what it is; its body its prose,
 * then Pilot's dots while a turn saves it (F35), or *Empty* while it has no text past its title,
 * as the handbook is born (F129.2). A read that fails, a draft's handbook included, reads "The
 * document did not load" (F113).
 */

import { useNavigate } from '@tanstack/react-router';
import { FileText, NotebookText, type LucideIcon } from 'lucide-react';
import { DidNotLoad, Overlay } from '@/components/overlay/overlay';
import { LinkedText } from '@/components/shared/linked-text';
import { Markdown } from '@/components/shared/markdown';
import { PilotWriting } from '@/components/timeline/writing';
import { useHandbook, useProjectDraft, type ProjectDocument } from '@/hooks/use-document';
import type { ProjectHead } from '@/hooks/use-projects';
import { isProse } from '@/hooks/use-timeline';

interface ProjectDocumentOverlayProps {
  projectId: string;
  /** The project's head, once read. */
  project: ProjectHead | undefined;
}

export function HandbookOverlay({ projectId, project }: ProjectDocumentOverlayProps) {
  const read = useHandbook(projectId);
  return <ReadOnlyOverlay projectId={projectId} project={project} read={read} showing="handbook" role="Handbook" icon={NotebookText} />;
}

export function ProjectDocumentOverlay({ projectId, project }: ProjectDocumentOverlayProps) {
  const read = useProjectDraft(projectId);
  return (
    <ReadOnlyOverlay
      projectId={projectId}
      project={project}
      read={read}
      showing="project-document"
      role="Project document"
      icon={FileText}
    />
  );
}

interface ReadOnlyOverlayProps extends ProjectDocumentOverlayProps {
  read: { data: ProjectDocument | undefined; error: unknown };
  showing: string;
  /** What it is, which titles it where its text gives no title. */
  role: string;
  icon: LucideIcon;
}

function ReadOnlyOverlay({ projectId, project, read: { data, error }, showing, role, icon: Icon }: ReadOnlyOverlayProps) {
  const navigate = useNavigate();
  const close = () => void navigate({ to: '/projects/$projectId', params: { projectId } });
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
      foot={null}
      onClose={close}
    >
      {failed ? <DidNotLoad /> : data && <Body document={data} />}
    </Overlay>
  );
}

function Body({ document }: { document: ProjectDocument }) {
  const prose = document.body.filter(isProse);
  return (
    <>
      {prose.length === 0 ? (
        <p className="item-sub" data-testid="overlay.empty">
          Empty
        </p>
      ) : (
        <div className="sheet-doc" data-testid="overlay.document">
          {prose.map((part, index) => (
            <Markdown key={index} text={part.markdown} />
          ))}
        </div>
      )}
      {document.writing && <PilotWriting />}
    </>
  );
}
