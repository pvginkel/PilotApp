/**
 * The project's menu at the end of its head (F2.4): what each standing offers, an archived
 * project only Bring back (D012); Join and Leave at once, each with its toast (F127, D011);
 * Finish, Reopen, Archive and Bring back, each asking first in a dialog with D010's texts,
 * Finish's and Archive's naming the running sessions they stop, no toast after (F5.1, F6, F128); the list and the head showing the new standing; the dialog
 * taking the focus to Cancel, holding it, and giving it back to the menu's button; everything
 * closed on another project (F1.6).
 */

import { test, expect } from '../support/fixtures';
import { makeUnique } from '../support/helpers';
import type { Projects } from '../support/projects';

type Spec = Omit<Parameters<Projects['make']>[0], 'name'>;

const PILOT_LINE = 'Pilot starts nothing more, and auto pilot’s permissions end with the project.';
const ARCHIVE_LINE = 'It leaves the project list for Archived, in the menu beside the list’s head.';

test.describe('The menu', () => {
  test('offers Join or Leave, Finish or Reopen, and Archive by the project’s standing; an archived project only Bring back', async ({
    people,
    projects,
    projectHead,
  }) => {
    const me = await people.signIn();
    const cases: [Spec, string[]][] = [
      [{ members: [me.handle!] }, ['Leave the project', 'Finish the project…', 'Archive the project']],
      [{ members: ['ada'] }, ['Join the project', 'Finish the project…', 'Archive the project']],
      [{ members: [me.handle!], state: 'finished' }, ['Leave the project', 'Reopen the project', 'Archive the project']],
      [{ members: ['ada'], state: 'draft' }, ['Join the project', 'Archive the project']],
      [{ members: [me.handle!], archived: true }, ['Bring back']],
      [{ members: ['ada'], state: 'finished', archived: true }, ['Bring back']],
    ];
    for (const [spec, items] of cases) {
      await projectHead.open(await projects.make({ name: makeUnique('Menu'), ...spec }));
      await expect(projectHead.menu).toHaveCount(0);
      await projectHead.menuButton.click();
      await expect(projectHead.menuItems).toHaveText(items);
    }
  });

  test('stands last in the head and closes on Esc and on a click outside it', async ({ page, people, projects, projectHead }) => {
    const me = await people.signIn();
    const id = await projects.make({ name: makeUnique('Closing'), members: [me.handle!], notes: [{ id: 'n', summary: 'S', content: 'C' }] });
    await projectHead.open(id);

    await expect(projectHead.menuButton).toHaveAccessibleName('The project’s menu');
    const [notes, menu] = [(await projectHead.notesButton.boundingBox())!, (await projectHead.menuButton.boundingBox())!];
    expect(menu.x).toBeGreaterThan(notes.x);

    await projectHead.menuButton.click();
    await expect(projectHead.menu).toBeVisible();
    await page.keyboard.press('Escape');
    await expect(projectHead.menu).toHaveCount(0);
    await projectHead.menuButton.click();
    await expect(projectHead.menu).toBeVisible();
    await projectHead.name.click();
    await expect(projectHead.menu).toHaveCount(0);
  });
});

test.describe('Join and Leave', () => {
  test('act at once, each with its toast, the project moving between the person’s projects and Other projects', async ({
    page,
    people,
    projects,
    projectHead,
    projectList,
  }) => {
    const me = await people.signIn({ name: 'Test Person' });
    const name = makeUnique('Joining');
    const id = await projects.make({ name, members: ['ada'] });
    await projectList.open(id);
    const others = projectList.group('others').root;
    const toast = (text: string) => page.getByTestId('app-shell.toast.item').getByText(text, { exact: true });
    await expect(projectList.tab(name, others)).toBeVisible();

    await projectHead.choose('join');
    await expect(toast(`You joined ${name}.`)).toBeVisible();
    await expect(projectList.tab(name, projectList.mine)).toBeVisible();
    await expect(projectList.tab(name, others)).toHaveCount(0);
    await expect(projectHead.members.locator('.avatar')).toHaveText(['AE', 'TP']);
    expect((await projects.head(id)).members.map((member) => member.handle)).toEqual(['ada', me.handle]);

    await projectHead.choose('leave');
    await expect(toast(`You left ${name}. It moves to Other projects.`)).toBeVisible();
    await expect(projectList.tab(name, others)).toBeVisible();
    await expect(projectList.tab(name, projectList.mine)).toHaveCount(0);
    await expect(projectHead.members.locator('.avatar')).toHaveText(['AE']);
    expect((await projects.head(id)).member).toBe(false);
    await projectHead.menuButton.click();
    await expect(projectHead.menuItems.first()).toHaveText('Join the project');
  });

  test('Leave on a finished project only says the person left, the project staying under Finished', async ({
    page,
    people,
    projects,
    projectHead,
    projectList,
  }) => {
    const me = await people.signIn({ name: 'Test Person' });
    const name = makeUnique('Leaving');
    const id = await projects.make({ name, state: 'finished', members: [me.handle!, 'ada'] });
    await projectList.open(id);
    const finished = projectList.group('finished').root;
    await expect(projectList.tab(name, finished)).toBeVisible();

    await projectHead.choose('leave');
    await expect(page.getByTestId('app-shell.toast.item').getByText(`You left ${name}.`, { exact: true })).toBeVisible();
    await expect(projectList.tab(name, finished)).toBeVisible();
    expect((await projects.head(id)).member).toBe(false);
  });
});

test.describe('Finish', () => {
  test('asks in a dialog what finishing does, the name linked; Esc, Cancel and a click beside it cancel', async ({
    page,
    people,
    projects,
    projectHead,
    links,
  }) => {
    const environment = makeUnique('env');
    await links.environment(environment, `${makeUnique('Lab')}-1`);
    const me = await people.signIn();
    const name = `${makeUnique('Port')} to pvginkel/Example`;
    const id = await projects.make({ name, members: [me.handle!], open_items: 3, environment_id: environment });
    await projectHead.open(id);
    const dialog = projectHead.dialog('finish');

    await projectHead.choose('finish');
    await expect(dialog.title).toHaveText(`Finish ${name}?`);
    await expect(dialog.title.getByRole('link', { name: 'pvginkel/Example' })).toHaveAttribute('href', 'https://github.com/pvginkel/Example');
    await expect(dialog.lines).toHaveText(['3 open items close unanswered.', PILOT_LINE]);
    await expect(dialog.note).toHaveText('The timeline and the chat stay, and the project can be reopened.');
    await expect(dialog.cancel).toHaveText('Cancel');
    await expect(dialog.confirm).toHaveText('Finish project');
    // No environments line and no YouTrack checkbox (X41), nothing about the notifications (D011).
    await expect(dialog.root.locator('input')).toHaveCount(0);
    await expect(dialog.root).not.toContainText(/environment|YouTrack|notif/i);

    await page.keyboard.press('Escape');
    await expect(dialog.root).toHaveCount(0);
    await projectHead.choose('finish');
    await dialog.cancel.click();
    await expect(dialog.root).toHaveCount(0);
    await projectHead.choose('finish');
    await dialog.backdrop.click({ position: { x: 5, y: 5 } });
    await expect(dialog.root).toHaveCount(0);
    expect((await projects.head(id)).state).toBe('open');
  });

  test('counts the open items that close unanswered, the line left out at none', async ({ people, projects, projectHead, links }) => {
    const environment = makeUnique('env');
    await links.environment(environment, `${makeUnique('Lab')}-1`);
    const me = await people.signIn();
    const one = await projects.make({ name: makeUnique('One'), members: [me.handle!], open_items: 1, environment_id: environment });
    const none = await projects.make({ name: makeUnique('None'), members: [me.handle!] });

    await projectHead.open(one);
    await projectHead.choose('finish');
    await expect(projectHead.dialog('finish').lines).toHaveText(['1 open item closes unanswered.', PILOT_LINE]);

    await projectHead.open(none);
    await projectHead.choose('finish');
    await expect(projectHead.dialog('finish').lines).toHaveText([PILOT_LINE]);
  });

  test('confirmed, finishes the project with auto pilot off, its open items closed and its archive question put; it moves under Finished, no toast', async ({
    page,
    people,
    projects,
    projectHead,
    projectList,
    links,
  }) => {
    const environment = makeUnique('env');
    await links.environment(environment, `${makeUnique('Lab')}-1`);
    const me = await people.signIn();
    const name = makeUnique('Finishing');
    const id = await projects.make({ name, members: [me.handle!], autopilot: true, open_items: 2, environment_id: environment });
    await projectList.open(id);
    await expect(projectHead.autopilot).toHaveAttribute('aria-checked', 'true');

    await projectHead.choose('finish');
    await projectHead.confirm('finish');
    await expect(projectHead.dialog('finish').root).toHaveCount(0);
    await expect(projectHead.finished).toHaveText('Finished');
    const head = await projects.head(id);
    expect([head.state, head.autopilot, head.open_items]).toEqual(['finished', false, 1]);
    const { items } = await projects.timeline(id);
    expect(items.filter((item) => item.done === null).map((item) => item.kind)).toEqual(['opening', 'archive_question']);

    const finishedAt = (await projects.list()).find((project) => project.id === id)!.finished_at!;
    const day = await page.evaluate((at) => new Intl.DateTimeFormat('en-GB', { day: 'numeric', month: 'short' }).format(new Date(at)), finishedAt);
    const finished = projectList.group('finished').root;
    // The tab's badge counts the archive question, its one open item.
    await expect(projectList.tab(name, finished).getByTestId('projects.tab.status')).toHaveText(`Finished ${day}1`);
    await expect(projectList.badge(name)).toHaveText('1');
    await expect(projectList.tab(name, projectList.mine)).toHaveCount(0);
    await expect(page.getByTestId('app-shell.toast.item')).toHaveCount(0);
  });

  test('refused, shows the reason and stays open', async ({ page, people, projects, projectHead }) => {
    const me = await people.signIn();
    const name = makeUnique('Raced');
    const id = await projects.make({ name, members: [me.handle!] });
    await projectHead.open(id);
    const dialog = projectHead.dialog('finish');

    await projectHead.choose('finish');
    await projects.transition(id, 'finished');
    await dialog.confirm.click();
    await expect(page.getByTestId('app-shell.toast.item').filter({ hasText: `Cannot finish ${name}` })).toBeVisible();
    await expect(dialog.root).toBeVisible();
    await expect(dialog.confirm).toBeEnabled();
    await dialog.cancel.click();
    await expect(dialog.root).toHaveCount(0);
  });
});

test.describe('Reopen', () => {
  test('asks in a dialog; confirmed, the project is back in its group with auto pilot off, no toast', async ({
    page,
    people,
    projects,
    projectHead,
    projectList,
  }) => {
    const me = await people.signIn();
    const name = makeUnique('Reopening');
    const id = await projects.make({ name, state: 'finished', members: [me.handle!] });
    await projectList.open(id);
    const dialog = projectHead.dialog('reopen');

    await projectHead.choose('reopen');
    await expect(dialog.title).toHaveText(`Reopen ${name}?`);
    await expect(dialog.lines).toHaveText(['Pilot takes the plan up where it stood.', 'Auto pilot stays off until you turn it on.']);
    await expect(dialog.note).toHaveCount(0);
    await expect(dialog.cancel).toHaveText('Cancel');
    await expect(dialog.confirm).toHaveText('Reopen project');
    await page.keyboard.press('Escape');
    await expect(dialog.root).toHaveCount(0);
    expect((await projects.head(id)).state).toBe('finished');

    await projectHead.choose('reopen');
    await projectHead.confirm('reopen');
    await expect(dialog.root).toHaveCount(0);
    await expect(projectHead.autopilot).toHaveAttribute('aria-checked', 'false');
    await expect(projectHead.finished).toHaveCount(0);
    await expect(projectList.tab(name, projectList.mine)).toBeVisible();
    const head = await projects.head(id);
    expect([head.state, head.autopilot]).toEqual(['open', false]);
    await expect(page.getByTestId('app-shell.toast.item')).toHaveCount(0);
  });
});

test.describe('Archive', () => {
  test('asks in a dialog; confirmed, a draft, an open and a finished project each leave the list for Archived, no toast', async ({
    page,
    people,
    projects,
    projectHead,
    projectList,
  }) => {
    const me = await people.signIn();
    const names: string[] = [];
    for (const state of ['draft', 'open', 'finished'] as const) {
      const name = makeUnique(`Archiving ${state}`);
      names.push(name);
      const id = await projects.make({ name, state, members: [me.handle!] });
      await projectList.open(id);
      const dialog = projectHead.dialog('archive');

      await projectHead.choose('archive');
      await expect(dialog.title).toHaveText(`Archive ${name}?`);
      await expect(dialog.lines).toHaveText([ARCHIVE_LINE]);
      await expect(dialog.note).toHaveText('Nothing is deleted: Bring back returns it where it was.');
      await expect(dialog.cancel).toHaveText('Cancel');
      await expect(dialog.confirm).toHaveText('Archive project');
      await expect(dialog.root).not.toContainText(/notif/i);
      await page.keyboard.press('Escape');
      await expect(dialog.root).toHaveCount(0);
      expect((await projects.head(id)).archived).toBe(false);

      await projectHead.choose('archive');
      await projectHead.confirm('archive');
      await expect(dialog.root).toHaveCount(0);
      await expect(projectHead.archived).toHaveText('Archived');
      await expect(projectList.tab(name)).toHaveCount(0);
      const head = await projects.head(id);
      expect([head.archived, head.state]).toEqual([true, state]);
      await projectHead.menuButton.click();
      await expect(projectHead.menuItems).toHaveText(['Bring back']);
      await expect(page.getByTestId('app-shell.toast.item')).toHaveCount(0);
    }

    await page.keyboard.press('Escape');
    await projectList.menuButton.click();
    await projectList.archivedItem.click();
    for (const name of names) await expect(projectList.tab(name, projectList.archived)).toBeVisible();
  });
});

test.describe('The running sessions', () => {
  test('Finish’s and Archive’s dialogs name the work items whose sessions they stop, a held one among them; confirmed, none runs', async ({
    page,
    people,
    projects,
    projectHead,
  }) => {
    const me = await people.signIn();
    const id = await projects.make({ name: makeUnique('Stopping'), members: [me.handle!] });
    const brief = { brief: 'Survey.', cwd: '/work/Example' };
    const running = await projects.startWork(id, { title: 'Surveying the stylesheets', ...brief });
    await expect.poll(async () => (await projects.work(id, running)).state).toBe('running');
    await projectHead.open(id);

    await projectHead.choose('finish');
    await expect(projectHead.dialog('finish').lines).toHaveText(['The running session stops: Surveying the stylesheets.', PILOT_LINE]);
    await page.keyboard.press('Escape');

    await projects.transition(id, 'paused');
    const held = await projects.startWork(id, { title: 'Renaming the badge', ...brief });
    await expect.poll(async () => (await projects.work(id, held)).state).toBe('held');
    await projectHead.open(id);
    const both = '2 running sessions stop: Surveying the stylesheets and Renaming the badge.';
    await projectHead.choose('finish');
    await expect(projectHead.dialog('finish').lines).toHaveText([both, PILOT_LINE]);
    await page.keyboard.press('Escape');
    await expect(projectHead.dialog('finish').root).toHaveCount(0);
    await projectHead.choose('archive');
    await expect(projectHead.dialog('archive').lines).toHaveText([both, ARCHIVE_LINE]);

    await projectHead.confirm('archive');
    for (const work of [running, held]) expect((await projects.work(id, work)).state).toBe('stopped');
  });
});

test.describe('Bring back', () => {
  test('asks in a dialog from the archived project’s menu; confirmed, it returns to the list where it was, no toast', async ({
    page,
    people,
    projects,
    projectHead,
    projectList,
  }) => {
    const me = await people.signIn();
    const [first, middle, last] = [makeUnique('First'), makeUnique('Middle'), makeUnique('Last')];
    const ids: string[] = [];
    for (const name of [first, middle, last]) ids.push(await projects.make({ name, members: [me.handle!] }));
    await projects.transition(ids[1], 'archived');
    await projectList.open(ids[0]);
    const mine = projectList.mine.getByTestId('projects.tab.name');
    await expect(mine).toHaveText([first, last]);

    await projectList.menuButton.click();
    await projectList.archivedItem.click();
    await projectList.tab(middle, projectList.archived).click();
    await expect(projectHead.archived).toBeVisible();
    const dialog = projectHead.dialog('bring-back');

    await projectHead.choose('bring-back');
    await expect(dialog.title).toHaveText(`Bring back ${middle}?`);
    await expect(dialog.lines).toHaveText(['It returns to the project list, where it was.']);
    await expect(dialog.note).toHaveCount(0);
    await expect(dialog.cancel).toHaveText('Cancel');
    await expect(dialog.confirm).toHaveText('Bring back');
    await expect(dialog.root).not.toContainText(/notif|store/i);
    await dialog.cancel.click();
    await expect(dialog.root).toHaveCount(0);
    expect((await projects.head(ids[1])).archived).toBe(true);

    await projectHead.choose('bring-back');
    await projectHead.confirm('bring-back');
    await expect(dialog.root).toHaveCount(0);
    await expect(projectHead.archived).toHaveCount(0);
    await expect(projectList.tab(middle, projectList.archived)).toHaveCount(0);
    expect((await projects.head(ids[1])).archived).toBe(false);
    await expect(page.getByTestId('app-shell.toast.item')).toHaveCount(0);

    await projectList.archivedBack.click();
    await expect(mine).toHaveText([first, middle, last]);
  });
});

test.describe('The dialog’s focus', () => {
  test('chosen with Enter, Finish, Archive, Reopen and Bring back each put the focus on Cancel', async ({ page, people, projects, projectHead }) => {
    const me = await people.signIn();
    const cases: [Spec, ('finish' | 'archive' | 'reopen' | 'bring-back')[]][] = [
      [{ members: [me.handle!] }, ['finish', 'archive']],
      [{ members: [me.handle!], state: 'finished' }, ['reopen']],
      [{ members: [me.handle!], archived: true }, ['bring-back']],
    ];
    for (const [spec, asks] of cases) {
      await projectHead.open(await projects.make({ name: makeUnique('Focus'), ...spec }));
      for (const ask of asks) {
        const dialog = projectHead.dialog(ask);
        await projectHead.chooseWithKeys(ask);
        await expect(dialog.root).toBeVisible();
        await expect(dialog.cancel).toBeFocused();
        await page.keyboard.press('Escape');
        await expect(dialog.root).toHaveCount(0);
        await expect(projectHead.menuButton).toBeFocused();
      }
    }
  });

  test('Tab and Shift+Tab stay inside the dialog', async ({ page, people, projects, projectHead }) => {
    const me = await people.signIn();
    await projectHead.open(await projects.make({ name: makeUnique('Trapped'), members: [me.handle!] }));
    const dialog = projectHead.dialog('finish');

    await projectHead.chooseWithKeys('finish');
    await expect(dialog.cancel).toBeFocused();
    await page.keyboard.press('Tab');
    await expect(dialog.confirm).toBeFocused();
    await page.keyboard.press('Tab');
    await expect(dialog.cancel).toBeFocused();
    await page.keyboard.press('Shift+Tab');
    await expect(dialog.confirm).toBeFocused();
    await page.keyboard.press('Shift+Tab');
    await expect(dialog.cancel).toBeFocused();
  });

  test('Esc or Cancel puts the focus back on the menu’s button', async ({ page, people, projects, projectHead }) => {
    const me = await people.signIn();
    const id = await projects.make({ name: makeUnique('Returning'), members: [me.handle!] });
    await projectHead.open(id);
    const dialog = projectHead.dialog('archive');

    await projectHead.chooseWithKeys('archive');
    await expect(dialog.cancel).toBeFocused();
    await page.keyboard.press('Escape');
    await expect(dialog.root).toHaveCount(0);
    await expect(projectHead.menuButton).toBeFocused();

    await projectHead.chooseWithKeys('archive');
    await expect(dialog.cancel).toBeFocused();
    await page.keyboard.press('Enter');
    await expect(dialog.root).toHaveCount(0);
    await expect(projectHead.menuButton).toBeFocused();
    expect((await projects.head(id)).archived).toBe(false);
  });
});

test.describe('Switching projects', () => {
  test('closes the menu and the dialog', async ({ page, people, projects, projectHead, projectList }) => {
    const me = await people.signIn();
    const a = await projects.make({ name: makeUnique('A'), members: [me.handle!] });
    const b = makeUnique('B');
    const bId = await projects.make({ name: b, members: [me.handle!] });
    await projectHead.open(a);
    await projectList.tab(b).click();
    await expect(page).toHaveURL(`/projects/${bId}`);

    // Back and Forward press nothing on the page: only another project closes what is open.
    await projectHead.menuButton.click();
    await expect(projectHead.menu).toBeVisible();
    await page.goBack();
    await expect(page).toHaveURL(`/projects/${a}`);
    await expect(projectHead.menuButton).toBeVisible();
    await expect(projectHead.menu).toHaveCount(0);

    await projectHead.choose('finish');
    await expect(projectHead.dialog('finish').root).toBeVisible();
    await page.goForward();
    await expect(page).toHaveURL(`/projects/${bId}`);
    await expect(projectHead.menuButton).toBeVisible();
    await expect(projectHead.dialog('finish').root).toHaveCount(0);
  });
});

test.describe('The menu on a narrow window', () => {
  test.use({ viewport: { width: 390, height: 844 }, hasTouch: true });

  test('the menu and its dialog stand within the window', async ({ people, projects, projectHead }) => {
    const me = await people.signIn();
    const id = await projects.make({ name: makeUnique('Phone'), members: [me.handle!] });
    await projectHead.open(id);

    await projectHead.menuButton.tap();
    const menu = (await projectHead.menu.boundingBox())!;
    expect(menu.x).toBeGreaterThanOrEqual(0);
    expect(menu.x + menu.width).toBeLessThanOrEqual(390);

    await projectHead.menuItem('archive').tap();
    const dialog = (await projectHead.dialog('archive').root.boundingBox())!;
    expect(dialog.x).toBeGreaterThanOrEqual(0);
    expect(dialog.x + dialog.width).toBeLessThanOrEqual(390);
  });
});
