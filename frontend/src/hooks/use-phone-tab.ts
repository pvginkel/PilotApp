/**
 * The phone's tab and the views pushed over it (F98.3 to F98.5), kept in the browser's history
 * entry and nothing of it in the browser's storage, so that Back and a reload find them. Leaving
 * the Timeline, or a draft's Chat in its place, is an entry of its own, pushed over the Timeline's;
 * a change between the other tabs replaces it, so that Back from any of them shows the Timeline,
 * and on the Timeline Back is the browser's own. An entry that keeps no tab shows the Timeline, and
 * every address gone to keeps none: a project opens on its Timeline, always, and a draft on its
 * Chat. A view, an address the project's route opens over its screen, is an entry of its own,
 * pushed over the one it was opened from, whose tab it keeps under it, a view over a view on top of
 * it; Back takes it off. A view's address reached cold — a notification's link, a link from another
 * app, a typed address — lies over the project's Timeline, an entry of the Timeline put under it,
 * so that Back lands there. The panel the desktop keeps per project is neither read nor changed.
 * A view keeps its scroll while another lies over it, as long as the page (R22): Back finds it
 * where it was left, and a view opened afresh, or reloaded, starts at its top.
 */

import { createContext, useLayoutEffect, useRef, useState } from 'react';
import { useLocation, useMatches, useRouter, type ParsedLocation } from '@tanstack/react-router';

/** `timeline` is a draft's Chat, the definition chat in the timeline's place. */
export type PhoneTab = 'timeline' | 'chat' | 'plan' | 'documents' | 'draft';

/** An open project's tabs and a draft's, in their order. */
export const PROJECT_TABS: readonly PhoneTab[] = ['timeline', 'chat', 'plan', 'documents'];
export const DRAFT_TABS: readonly PhoneTab[] = ['timeline', 'draft', 'documents'];

declare module '@tanstack/react-router' {
  interface HistoryState {
    /** The phone's tab at the entry, none for the Timeline; at a view's, the tab under the views. */
    phoneTab?: Exclude<PhoneTab, 'timeline'>;
    /** The entry was pushed over its address's Timeline, which Back shows. */
    overTimeline?: boolean;
    /** At a view's entry, the views at it by their addresses, bottom to top, its own last. */
    phoneViews?: string[];
  }
}

/** A view on the phone, as the views the project's screen shows give it to what it shows. */
export interface PhoneView {
  /** Takes it off, showing what lay under it. */
  back: () => void;
  /** The address of the view under it, none where it lies on a tab. */
  under: string | null;
  /** Its scroll as it was left, 0 for a view not shown before. */
  scroll: number;
  /** Keeps its scroll as it scrolls. */
  keep: (top: number) => void;
}

/** The view showing on a phone; none off one. */
export const PhoneViewContext = createContext<PhoneView | null>(null);

interface PhoneScreen {
  tab: PhoneTab;
  /** Shows the tab, the views over it taken off first. */
  show: (tab: PhoneTab) => void;
  /** The views showing, bottom to top, by their addresses. */
  views: readonly string[];
  /** Takes the view on top off. */
  back: () => void;
  /** The view on top's scroll as it was left, and its keep. */
  scroll: number;
  keep: (top: number) => void;
}

/** Each view's scroll, by the key of its entry in the browser's history. */
const scrolls = new Map<string, number>();

/** What an entry shows on a phone: the tab under the views, and the views. */
interface Shown {
  location: ParsedLocation;
  /** Whether a view shows at it. */
  overlaid: boolean;
  /** The tab as the entry keeps it, none for the Timeline. */
  kept: Exclude<PhoneTab, 'timeline'> | undefined;
  views: string[];
  /** A view's entry that does not say so yet: pushed over the entry before it, or reached cold. */
  unsaid: 'pushed' | 'cold' | null;
}

function shownAt(location: ParsedLocation, overlaid: boolean, below: Shown | null): Shown {
  const { state } = location;
  const shown = { location, overlaid, kept: state.phoneTab, unsaid: null };
  if (!overlaid) return { ...shown, views: [] };
  if (state.phoneViews !== undefined) return { ...shown, views: state.phoneViews };
  if (below !== null && below.location.state.__TSR_index === state.__TSR_index - 1) {
    return { ...shown, kept: below.kept, views: [...below.views, location.pathname], unsaid: 'pushed' };
  }
  return { ...shown, kept: undefined, views: [location.pathname], unsaid: 'cold' };
}

/** The tab of the project's screen and the views over it, a draft's if `draft`, a view showing if `overlaid`. */
export function usePhoneTab(projectId: string, draft: boolean, overlaid: boolean): PhoneScreen {
  const router = useRouter();
  const location = useLocation();
  const matched = useMatches({ select: (matches) => matches.at(-1)?.pathname });
  // The entry the screen shows, and the one it showed before. The router takes a new location
  // before it draws its matches, which `overlaid` tells of: until then the screen stays as it was.
  const [screen, setScreen] = useState<{ shown: Shown; below: Shown | null } | null>(null);
  let current = screen;
  const settled = location.pathname === matched;
  if (current === null || (settled && (current.shown.location.state.__TSR_key !== location.state.__TSR_key || current.shown.overlaid !== overlaid))) {
    const below = current === null ? null : current.shown.location.state.__TSR_key === location.state.__TSR_key ? current.below : current.shown;
    current = { shown: shownAt(location, overlaid, below), below };
    setScreen(current);
  }
  const { shown } = current;
  const { kept, views } = shown;
  // A tab the project has not, a draft's Draft past Create, shows the Timeline.
  const tab = kept !== undefined && (draft ? DRAFT_TABS : PROJECT_TABS).includes(kept) ? kept : 'timeline';

  // The tab to show once Back has taken the views off.
  const afterViews = useRef<PhoneTab | null>(null);
  const show = (to: PhoneTab) => {
    const { history } = router;
    if (views.length > 0) {
      afterViews.current = to;
      history.go(-views.length);
      return;
    }
    if (to === tab) return;
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

  // The entry a view's address opened at says it is one, once.
  const said = useRef<string | undefined>(undefined);
  useLayoutEffect(() => {
    if (!settled) return;
    if (views.length === 0 && afterViews.current !== null) {
      const to = afterViews.current;
      afterViews.current = null;
      show(to);
    }
    const { history } = router;
    const key = shown.location.state.__TSR_key;
    if (shown.unsaid === null || said.current === key || history.location.state.__TSR_key !== key) return;
    said.current = key;
    const own = { phoneTab: kept, phoneViews: views };
    const href = history.location.href;
    if (shown.unsaid === 'pushed') {
      history.replace(href, own);
      return;
    }
    history.replace(router.buildLocation({ to: '/projects/$projectId', params: { projectId } }).href, {});
    // The browser takes both a microtask later, as one entry, unless the first is taken now.
    history.flush();
    history.push(href, own);
  });

  // The history keys every entry, the page's first included.
  const entry = shown.location.state.__TSR_key!;
  return {
    tab,
    show,
    views,
    back: () => router.history.back(),
    scroll: scrolls.get(entry) ?? 0,
    keep: (top) => void scrolls.set(entry, top),
  };
}
