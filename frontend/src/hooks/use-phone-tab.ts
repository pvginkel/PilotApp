/**
 * The phone's tab (F98.3, F98.5): what shows between a project's head and the tabs at the bottom,
 * kept in the browser's history entry and nothing of it in the browser's storage, so that Back and
 * a reload find it. Leaving the Timeline, or a draft's Chat in its place, is an entry of its own,
 * pushed over the Timeline's; a change between the other tabs replaces it, so that Back from any of
 * them shows the Timeline, and on the Timeline Back is the browser's own. An entry that keeps no tab
 * shows the Timeline, and every address gone to keeps none: a project opens on its Timeline, always,
 * and a draft on its Chat. The panel the desktop keeps per project is neither read nor changed.
 */

import { useRouter, useRouterState } from '@tanstack/react-router';

/** `timeline` is a draft's Chat, the definition chat in the timeline's place. */
export type PhoneTab = 'timeline' | 'chat' | 'plan' | 'documents' | 'draft';

/** An open project's tabs and a draft's, in their order. */
export const PROJECT_TABS: readonly PhoneTab[] = ['timeline', 'chat', 'plan', 'documents'];
export const DRAFT_TABS: readonly PhoneTab[] = ['timeline', 'draft', 'documents'];

declare module '@tanstack/react-router' {
  interface HistoryState {
    /** The phone's tab at the entry, none for the Timeline. */
    phoneTab?: Exclude<PhoneTab, 'timeline'>;
    /** The entry was pushed over its address's Timeline, which Back shows. */
    overTimeline?: boolean;
  }
}

interface PhoneTabState {
  tab: PhoneTab;
  /** Shows the tab; over an overlay, at the project's own address. */
  show: (tab: PhoneTab) => void;
}

/** The tab of the project's screen, a draft's if `draft`, under an overlay if `overlaid`. */
export function usePhoneTab(projectId: string, draft: boolean, overlaid: boolean): PhoneTabState {
  const router = useRouter();
  const kept = useRouterState({ select: (state) => state.location.state.phoneTab });
  // A tab the project has not, a draft's Draft past Create, shows the Timeline.
  const tab = kept !== undefined && (draft ? DRAFT_TABS : PROJECT_TABS).includes(kept) ? kept : 'timeline';
  const show = (to: PhoneTab) => {
    if (overlaid) {
      void router.navigate({ to: '/projects/$projectId', params: { projectId }, state: to === 'timeline' ? undefined : { phoneTab: to } });
      return;
    }
    if (to === tab) return;
    const { history } = router;
    const { href, state } = history.location;
    if (to === 'timeline') {
      if (state.overTimeline === true) history.back();
      else history.replace(href, {});
    } else if (tab === 'timeline') {
      history.push(href, { phoneTab: to, overTimeline: true });
    } else {
      history.replace(href, { phoneTab: to, overTimeline: state.overTimeline });
    }
  };
  return { tab, show };
}
