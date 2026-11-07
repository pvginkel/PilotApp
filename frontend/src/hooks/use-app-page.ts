/**
 * This page of Pilot in front of its person (F94.3, F142, F147; DB 312, 314).
 *
 * Nothing is dismissed by push: the page closes, on its own device, the notifications of what it
 * shows. While it is visible a page of a project closes that project's notification, under the
 * project's id, as it comes to show the project; and any page of Pilot closes the alarms', on a
 * fresh load and on coming back to the foreground.
 *
 * Its beat says its person is online: every thirty seconds while the page is visible and has had a
 * key, a pointer, a touch or a scroll in the last two minutes, and at once when the project it
 * shows changes. Hidden, or two minutes without input, it sends its away, by beacon, so that it
 * gets out as the page hides; the server's ninety seconds end a page whose away is lost. Only a
 * person with a handle beats: the server refuses a page before it. Its ui state, `shell.app-page`,
 * is ready once the page hears its person's input.
 */

import { useEffect, useRef } from 'react';
import { useParams } from '@tanstack/react-router';
import { api } from '@/lib/api/generated/client';
import { isPerson, type Self } from '@/hooks/use-self';
import { useUiStateInstrumentation } from '@/lib/test/ui-state';

/** The `tag` the server pushes every person's alarms under (F142). */
const ALARMS_TAG = 'alarms';

const BEAT_MS = 30_000;
const IDLE_MS = 120_000;

/**
 * A key, a pointer, a touch or a scroll, heard in the capture phase. A person's scroll comes as a
 * wheel, a touch or a key: the `scroll` event fires for the app's own scrolling too.
 */
const INPUTS = ['keydown', 'pointerdown', 'pointermove', 'touchstart', 'wheel'] as const;

/** Notifications on this device: absent outside a secure context, as on the dev server reached by its address. */
const NOTIFIES = 'serviceWorker' in navigator && 'Notification' in window;

function visible(): boolean {
  return document.visibilityState === 'visible';
}

/** Closes this device's notifications under `tags`; none stands before the service worker is registered. */
async function closeNotifications(tags: readonly string[]): Promise<void> {
  const registration = await navigator.serviceWorker.getRegistration();
  if (registration === undefined) return;
  for (const tag of tags) {
    for (const notification of await registration.getNotifications({ tag })) notification.close();
  }
}

/** The page's beat and its away, while it is mounted for a person with a handle. */
class AppPage {
  /** The page's id, minted by its first beat; none before it and after its away. */
  private id: string | null = null;
  private active = false;
  private lastInput = -Infinity;
  private beatTimer: number | undefined;
  private idleTimer: number | undefined;
  /** A beat in flight, and another asked for while it is. */
  private syncing = false;
  private again = false;

  private project: string | null;

  constructor(project: string | null) {
    this.project = project;
  }

  start(): void {
    for (const type of INPUTS) window.addEventListener(type, this.input, { capture: true, passive: true });
    document.addEventListener('visibilitychange', this.visibility);
  }

  stop(): void {
    for (const type of INPUTS) window.removeEventListener(type, this.input, { capture: true });
    document.removeEventListener('visibilitychange', this.visibility);
    this.goAway();
  }

  show(project: string | null): void {
    if (project === this.project) return;
    this.project = project;
    if (this.active) void this.sync();
  }

  private input = (): void => {
    this.lastInput = performance.now();
    if (visible()) this.goActive();
  };

  private visibility = (): void => {
    if (!visible()) this.goAway();
    else if (performance.now() - this.lastInput < IDLE_MS) this.goActive();
  };

  private goActive(): void {
    if (this.active) return;
    this.active = true;
    this.beatTimer = window.setInterval(() => void this.sync(), BEAT_MS);
    this.armIdle(IDLE_MS - (performance.now() - this.lastInput));
    void this.sync();
  }

  private armIdle(delay: number): void {
    this.idleTimer = window.setTimeout(() => {
      const idle = performance.now() - this.lastInput;
      if (idle >= IDLE_MS) this.goAway();
      else this.armIdle(IDLE_MS - idle);
    }, delay);
  }

  private goAway(): void {
    if (!this.active) return;
    this.active = false;
    window.clearInterval(this.beatTimer);
    window.clearTimeout(this.idleTimer);
    void this.sync();
  }

  /**
   * Brings the server to the page: a beat while active, else the away of the page it has. The away
   * goes before the first await, so that it gets out inside the event that hid the page.
   */
  private async sync(): Promise<void> {
    if (this.syncing) {
      this.again = true;
      return;
    }
    this.syncing = true;
    try {
      do {
        this.again = false;
        if (this.active) await this.beat();
        else if (this.id !== null) {
          navigator.sendBeacon(`/api/people/self/app-pages/${this.id}/away`);
          this.id = null;
        }
      } while (this.again);
    } finally {
      this.syncing = false;
    }
  }

  /** A beat; a page the server has ended, by its away or its ninety seconds, beats afresh. */
  private async beat(): Promise<void> {
    const body = { project_id: this.project };
    try {
      if (this.id !== null) {
        const { response } = await api.PUT('/api/people/self/app-pages/{page_id}', { params: { path: { page_id: this.id } }, body });
        if (response.status !== 404) return;
      }
      const { data } = await api.POST('/api/people/self/app-pages', { body });
      this.id = data?.id ?? null;
    } catch (error) {
      // A beat the network lost is a beat missed: the next goes at its time.
      if (!(error instanceof TypeError)) throw error;
    }
  }
}

/** This page in front of `self`, under the shell: the notifications it closes and its beat. */
export function useAppPage(self: Self | undefined): void {
  const projectId = useParams({ strict: false, select: (params) => params.projectId ?? null });
  const person = self !== undefined && isPerson(self);
  const shown = useRef<string | null>(null);
  const page = useRef<AppPage | null>(null);

  useEffect(() => {
    shown.current = projectId;
    if (NOTIFIES && projectId !== null && visible()) void closeNotifications([projectId]);
    page.current?.show(projectId);
  }, [projectId]);

  useEffect(() => {
    if (!NOTIFIES) return;
    // A fresh load's project is closed above, as it comes to show.
    if (visible()) void closeNotifications([ALARMS_TAG]);
    const foreground = () => {
      if (visible()) void closeNotifications(shown.current === null ? [ALARMS_TAG] : [ALARMS_TAG, shown.current]);
    };
    document.addEventListener('visibilitychange', foreground);
    return () => document.removeEventListener('visibilitychange', foreground);
  }, []);

  useEffect(() => {
    if (!person) return;
    const beating = new AppPage(shown.current);
    page.current = beating;
    beating.start();
    return () => {
      beating.stop();
      page.current = null;
    };
  }, [person]);
  useUiStateInstrumentation('shell.app-page', { isLoading: !person });
}
