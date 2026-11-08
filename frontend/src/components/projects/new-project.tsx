/**
 * A new project, the plus's (F46.1; D174, on its first message): its definition chat,
 * "Tell Pilot what to manage", with nothing behind it on the server, its composer over its foot, the
 * focus in its field; over it the draft's head, "New project" and its Draft chip, and beside it the
 * panel's Draft and Documents, both empty; on a phone the tabs at the bottom, a draft's. The first
 * message sent makes the draft (`useStartProject`), which the page then shows at its address,
 * `draft-<number>`, in this entry's place, the focus in its chat's field, its composer waiting until
 * the draft's chats are read and the route shows them (`screen-reads.ts`). Until then the server holds
 * nothing of it, so leaving leaves nothing behind; a message the server refuses makes nothing
 * either, its words left in the field. They are kept in the browser until sent (F133).
 */

import { useEffect, useRef, useState, type Ref } from 'react';
import { useNavigate } from '@tanstack/react-router';
import { ChatEmptyState } from '@/components/chat/chat-empty-state';
import { ComposerBox } from '@/components/chat/composer';
import { ChatColumn } from '@/components/chat/project-chat';
import { NewPanel, NewPhonePanel, type NewPanelTab } from '@/components/panel/panel';
import { PanelDivider } from '@/components/panel/panel-divider';
import { PhoneTabs } from '@/components/projects/phone-project';
import { DrawerButton } from '@/components/shell/drawer';
import { useStartProject } from '@/hooks/use-chats';
import { discussIn } from '@/hooks/use-discuss';
import { usePhone } from '@/hooks/use-phone';
import { usePhoneTab } from '@/hooks/use-phone-tab';
import { knowAt } from '@/hooks/use-project-address';
import { useUnsentText } from '@/hooks/use-unsent-text';

/** The words not sent yet, as the browser keeps them. */
const UNSENT = 'chat/new-project';

export function NewProject() {
  return usePhone() ? <PhoneNewProject /> : <DeskNewProject />;
}

function DeskNewProject() {
  const [tab, setTab] = useState<NewPanelTab>('draft');
  const [head, setHead] = useState<HTMLElement | null>(null);
  const [page, setPage] = useState<HTMLElement | null>(null);
  return (
    <div ref={setPage} className="project">
      <div className="project-main">
        <NewHead ref={setHead} />
        <div className="stage">
          <NewChat covered={false} />
        </div>
      </div>
      <PanelDivider project={page} draft />
      <NewPanel tab={tab} head={head} onTab={setTab} />
    </div>
  );
}

function PhoneNewProject() {
  const { tab, show } = usePhoneTab(true, false);
  return (
    <div className="project">
      <div className="project-main">
        <NewHead phone />
        <div className="phone-page" data-tab={tab} data-testid="project.phone-page">
          <NewChat covered={tab !== 'timeline'} />
          {(tab === 'draft' || tab === 'documents') && <NewPhonePanel tab={tab} />}
        </div>
        <PhoneTabs draft tab={tab} count={0} unread={false} onTab={show} />
      </div>
    </div>
  );
}

/** A draft's head with no draft yet: its name, "New project", and the Draft chip; on a phone the drawer's button first. */
function NewHead({ phone = false, ref }: { phone?: boolean; ref?: Ref<HTMLElement> }) {
  return (
    <header ref={ref} className={phone ? 'feed-head phone-head' : 'feed-head'} data-testid="project.head">
      {phone && <DrawerButton />}
      <h1 data-testid="project.name">New project</h1>
      <span className="chip draft-chip" data-testid="project.draft">
        Draft
      </span>
      <div className="grow" />
    </header>
  );
}

function NewChat({ covered }: { covered: boolean }) {
  return (
    <ChatColumn home="feed" covered={covered} composer={<NewComposer />}>
      <ChatEmptyState home="feed" />
    </ChatColumn>
  );
}

function NewComposer() {
  const { text, change } = useUnsentText(UNSENT);
  const start = useStartProject();
  const navigate = useNavigate();
  const field = useRef<HTMLTextAreaElement>(null);
  const [moving, setMoving] = useState(false);
  const words = text.trim();
  const sendable = !start.pending && !moving && words !== '';

  useEffect(() => field.current!.focus(), []);

  const send = () => {
    field.current!.focus();
    if (!sendable) return;
    void start.act(words).then((draft) => {
      if (draft === null) return;
      change('');
      knowAt(draft.address, draft.id);
      // As Discuss asks for it, with nothing quoted: the draft's composer takes the focus once drawn.
      discussIn(draft.id, null);
      setMoving(true);
      void navigate({ to: '/projects/$address', params: { address: draft.address }, replace: true });
    });
  };

  return <ComposerBox home="feed" field={field} text={text} onChange={change} onSend={send} sendable={sendable} waiting={start.pending || moving} />;
}
