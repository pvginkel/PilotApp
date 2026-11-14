/**
 * A done work item's debrief in the overlay (F26.9), at its own address under the session log's,
 * opening where the session log opens and as it does: off a phone its popover over the tab
 * showing, on a phone a view. Its head is "Debrief" over the item's title and the time its turn
 * ended, and Full debrief; its body the stage session's own debrief, as prose the frame's full
 * width. Full debrief shows the full debrief at its address under the debrief's (F26.10), off a
 * phone in the same frame, taller, its head's arrow back to the debrief, on a phone a view pushed
 * over the debrief's. Its head is "Full debrief" over the item's title; its body first the
 * sections as a table, a row per section — its name on one line, cut short with an ellipsis, its
 * rounds, its time — that goes to its section, then the sections, each entry in the order given
 * with its role and its time: its words, or its pass or fail, muted, a fail in the warning's
 * colour, or neither, muted; an entry with a why opens its round with it. The sections, their
 * rounds and their times are the read's, shown as given (D159). An address that names no work item
 * of the project, or one with no debrief, reads "The debrief did not load".
 */

import { useRef } from 'react';
import { Link } from '@tanstack/react-router';
import { ArrowLeft, ChevronRight, NotebookPen } from 'lucide-react';
import { DidNotLoad, Overlay } from '@/components/overlay/overlay';
import { scrollToIn } from '@/components/overlay/scroll-to';
import { LinkedText } from '@/components/shared/linked-text';
import { Markdown } from '@/components/shared/markdown';
import { Time } from '@/components/shared/time';
import { useTabReplace } from '@/hooks/use-doc-tabs';
import { useOverlayClose } from '@/hooks/use-overlay-close';
import { usePhone } from '@/hooks/use-phone';
import { useShownProject } from '@/hooks/use-project-address';
import { titleOf, type TimelineItem } from '@/hooks/use-timeline';
import { useGetItemsDebriefByItemId, useGetProjectsTimelineByProjectId } from '@/lib/api/generated/hooks';
import type { components } from '@/lib/api/generated/types';
import { smoothly } from '@/lib/motion';
import { useUiStateInstrumentation } from '@/lib/test/ui-state';
import { cn } from '@/lib/utils';

type Section = components['schemas']['DebriefSchema.1fdd8ae.DebriefSectionSchema'];
type Entry = components['schemas']['DebriefSchema.1fdd8ae.DebriefEntrySchema'];

interface DebriefOverlayProps {
  projectId: string;
  /** The work item's id, its session's. */
  sessionId: string;
  /** The full debrief, in the debrief's place. */
  full: boolean;
}

export function DebriefOverlay({ projectId, sessionId, full }: DebriefOverlayProps) {
  const close = useOverlayClose();
  const phone = usePhone();
  const { address } = useShownProject();
  const replace = useTabReplace();
  const body = useRef<HTMLDivElement>(null);
  const timeline = useGetProjectsTimelineByProjectId({ path: { project_id: projectId } });
  const debrief = useGetItemsDebriefByItemId({ path: { item_id: sessionId } });
  useUiStateInstrumentation('overlay.debrief', { isLoading: debrief.isLoading, error: debrief.error });
  const item = timeline.data?.items.find((each) => each.id === sessionId && each.kind === 'work');
  const failed = timeline.error !== null || debrief.error !== null || (timeline.data !== undefined && item === undefined);
  const params = { address, sessionId };
  return (
    <Overlay
      showing={`${full ? 'full debrief' : 'debrief'} ${sessionId}`}
      titles={!failed && item && <Titles item={item} full={full} />}
      back={
        full && !phone ? (
          <Link
            to="/projects/$address/sessions/$sessionId/debrief"
            params={params}
            replace={replace}
            className="btn btn-ghost btn-sm btn-icon"
            title="Back to the debrief"
            aria-label="Back"
            data-testid="overlay.back"
          >
            <ArrowLeft className="icon" aria-hidden="true" />
          </Link>
        ) : null
      }
      tall={full}
      acts={
        !full &&
        !failed &&
        debrief.data && (
          <Link
            to="/projects/$address/sessions/$sessionId/debrief/full"
            params={params}
            replace={replace}
            className="btn btn-ghost btn-sm debrief-more"
            title="Every agent’s debrief, per section and round"
            data-testid="debrief.full"
          >
            Full debrief
            <ChevronRight className="icon" aria-hidden="true" />
          </Link>
        )
      }
      foot={null}
      onClose={close}
      bodyRef={body}
    >
      {failed ? (
        <DidNotLoad what="The debrief" />
      ) : (
        item &&
        debrief.data &&
        (full ? (
          <FullDebrief
            sections={debrief.data.sections}
            goTo={(section) => scrollToIn(body.current!, body.current!.querySelectorAll<HTMLElement>('.db-section')[section], smoothly())}
          />
        ) : (
          <div data-testid="debrief">
            <Markdown text={debrief.data.debrief} />
          </div>
        ))
      )}
    </Overlay>
  );
}

function Titles({ item, full }: { item: TimelineItem; full: boolean }) {
  return (
    <>
      <h2 data-testid="overlay.title">
        <NotebookPen className="icon" aria-hidden="true" /> {full ? 'Full debrief' : 'Debrief'}
      </h2>
      <div className="sub" data-testid="overlay.sub">
        <span data-testid="debrief.item">
          <LinkedText text={titleOf(item)} />
        </span>
        {!full && item.done !== null && (
          <>
            <span>·</span>
            <Time at={item.done.at} format="clock" testId="debrief.ended" />
          </>
        )}
      </div>
    </>
  );
}

/** Every entry in its section, after the table of the sections, whose rows go to them. */
function FullDebrief({ sections, goTo }: { sections: Section[]; goTo: (section: number) => void }) {
  return (
    <div data-testid="debrief.sections">
      <table className="db-index" data-testid="debrief.index">
        <thead>
          <tr>
            <th>Section</th>
            <th>Rounds</th>
            <th>Time</th>
          </tr>
        </thead>
        <tbody>
          {sections.map((section, index) => (
            <tr key={index} onClick={() => goTo(index)} data-testid="debrief.index.row">
              {/* The whole name its tooltip, where the cell cuts it short. */}
              <td title={section.name}>
                <button type="button" data-testid="debrief.index.name">
                  {section.name}
                </button>
              </td>
              <td data-testid="debrief.index.rounds">{section.rounds > 1 ? <b>{section.rounds}</b> : section.rounds}</td>
              <td data-testid="debrief.index.time">{took(section.duration)}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {sections.map((section, index) => (
        <section key={index} className="db-section" data-testid="debrief.section">
          <h3 data-testid="debrief.section.name">{section.name}</h3>
          <ol className="db-entries">
            {section.entries.map((entry, at) => (
              <EntryLines key={at} entry={entry} />
            ))}
          </ol>
        </section>
      ))}
    </div>
  );
}

/** An entry, after the line that opens its round where it gives the round's why. */
function EntryLines({ entry }: { entry: Entry }) {
  const said = entry.words !== null;
  return (
    <>
      {entry.why !== null && (
        <li className="db-round" data-testid="debrief.round">
          <span className="round-n">Round {entry.round}</span>
          <span className="why" data-testid="debrief.round.why">
            <LinkedText text={entry.why} />
          </span>
        </li>
      )}
      <li className={cn('db-entry', !said && 'figure')} data-testid="debrief.entry">
        <div className="db-who">
          {said ? <b data-testid="debrief.entry.role">{entry.role}</b> : <span data-testid="debrief.entry.role">{entry.role}</span>}
          <span className="db-meta">
            <span data-testid="debrief.entry.time">{took(entry.duration)}</span>
            {entry.passed !== null && (
              <span className={cn('outcome', !entry.passed && 'failed')} data-testid="debrief.entry.result">
                {entry.passed ? 'passed' : 'failed'}
              </span>
            )}
          </span>
        </div>
        {said && <Markdown text={entry.words!} className="db-text" />}
      </li>
    </>
  );
}

/** A time in whole seconds as the full debrief shows it: "<1m", "17m", "1h 40m". */
function took(seconds: number): string {
  if (seconds < 60) return '<1m';
  const minutes = Math.round(seconds / 60);
  if (minutes < 60) return `${minutes}m`;
  return `${Math.floor(minutes / 60)}h ${String(minutes % 60).padStart(2, '0')}m`;
}
