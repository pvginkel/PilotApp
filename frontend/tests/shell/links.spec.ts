/**
 * Links in text (F91, F93): a ticket id by the deployment's pattern and URL template, a repo
 * written pvginkel/Name to GitHub, an environment by its id's form or by a name of the record's to
 * KubeCoder's Open; in the colour of the text around them, underlined under the mouse; unlinked
 * while a setting is unset. A project's tab is the first text they show in: an <a> itself, so each
 * is a span that opens it.
 *
 * The ticket and KubeCoder addresses are the backend's own, so a link opened in a popup loads.
 */

import { test, expect } from '../support/fixtures';
import { makeUnique, makeUniqueToken } from '../support/helpers';

const ENVIRONMENT_ID = 'pvginkel-example-1a2b3c';

test.describe('Links in text', () => {
  test('a ticket id, a repo and an environment link in a tab, each a span that opens it', async ({
    page,
    backendUrl,
    people,
    projects,
    projectList,
    links,
  }) => {
    await links.set({ ticket_url_template: `${backendUrl}/tickets/{id}`, environment_link_base_url: `${backendUrl}/kubecoder` });
    const lab = { id: makeUnique('env'), name: `${makeUnique('Lab')}-1` };
    await links.environment(lab.id, lab.name);
    const me = await people.signIn();
    const onScreen = await projects.make({ name: makeUnique('On screen'), members: [me.handle!] });
    const name = `${makeUnique('Port')} to pvginkel/Example`;
    const title = `Restart ${lab.name} and ${ENVIRONMENT_ID}`;
    await projects.make({ name, ticket: 'PL-7', members: [me.handle!], tasks: [{ id: 'a', title, status: 'in_progress' }] });
    await projectList.open(onScreen);

    const tab = projectList.tab(name);
    const ticket = tab.getByTestId('projects.tab.ticket').getByRole('link', { name: 'PL-7' });
    const status = tab.getByTestId('projects.tab.status');
    const environment = status.getByRole('link', { name: lab.name });
    const kubecoder = `${backendUrl}/kubecoder/environments`;
    await expect(ticket).toHaveAttribute('data-href', `${backendUrl}/tickets/PL-7`);
    await expect(tab.getByTestId('projects.tab.name').getByRole('link', { name: 'pvginkel/Example' })).toHaveAttribute(
      'data-href',
      'https://github.com/pvginkel/Example',
    );
    await expect(environment).toHaveAttribute('data-href', `${kubecoder}/${lab.id}/ssh/open`);
    await expect(status.getByRole('link', { name: ENVIRONMENT_ID })).toHaveAttribute(
      'data-href',
      `${kubecoder}/${ENVIRONMENT_ID}/ssh/open`,
    );
    await expect(status).toHaveText(title);

    // A click opens the ticket, and not the tab around it.
    const clicked = page.waitForEvent('popup');
    await ticket.click();
    expect((await clicked).url()).toBe(`${backendUrl}/tickets/PL-7`);
    await expect(page).toHaveURL(`/projects/${onScreen}`);

    // Enter on a focused one opens it too.
    await environment.focus();
    const entered = page.waitForEvent('popup');
    await page.keyboard.press('Enter');
    expect((await entered).url()).toBe(`${kubecoder}/${lab.id}/ssh/open`);
    await expect(page).toHaveURL(`/projects/${onScreen}`);
  });

  test('a link has the colour of the text around it and underlines under the mouse', async ({
    backendUrl,
    people,
    projects,
    projectList,
    links,
  }) => {
    await links.set({ ticket_url_template: `${backendUrl}/tickets/{id}` });
    const me = await people.signIn();
    const name = makeUnique('Coloured');
    const id = await projects.make({ name, ticket: 'PL-7', members: [me.handle!] });
    await projectList.open(id);

    const around = projectList.tab(name).getByTestId('projects.tab.ticket');
    const ticket = around.getByRole('link', { name: 'PL-7' });
    await expect(ticket).toBeVisible();
    const style = (property: string) =>
      ticket.evaluate((element, name) => getComputedStyle(element).getPropertyValue(name), property);
    expect(await style('color')).toBe(await around.evaluate((element) => getComputedStyle(element).color));
    expect(await style('text-decoration-line')).toBe('none');
    await ticket.hover();
    await expect.poll(() => style('text-decoration-line')).toBe('underline');
  });

  test('an environment name without a number links only as “the … environment”', async ({
    backendUrl,
    people,
    projects,
    projectList,
    links,
  }) => {
    await links.set({ environment_link_base_url: `${backendUrl}/kubecoder` });
    const shed = { id: makeUnique('env'), name: `Shed${makeUniqueToken()}` };
    await links.environment(shed.id, shed.name);
    const me = await people.signIn();
    const name = `${shed.name} notes`;
    const title = `Tidy the ${shed.name} environment`;
    const id = await projects.make({ name, members: [me.handle!], tasks: [{ id: 'a', title, status: 'in_progress' }] });
    await projectList.open(id);

    const tab = projectList.tab(name);
    await expect(tab.getByTestId('projects.tab.status').getByRole('link', { name: shed.name })).toHaveAttribute(
      'data-href',
      `${backendUrl}/kubecoder/environments/${shed.id}/ssh/open`,
    );
    await expect(tab.getByTestId('projects.tab.name').getByRole('link')).toHaveCount(0);
  });

  test('with the settings unset, a ticket id and an environment show unlinked, and a repo still links', async ({
    people,
    projects,
    projectList,
    links,
  }) => {
    await links.set({});
    const lab = { id: makeUnique('env'), name: `${makeUnique('Lab')}-1` };
    await links.environment(lab.id, lab.name);
    const me = await people.signIn();
    const name = `${makeUnique('Unlinked')} on pvginkel/Example`;
    const title = `Restart ${lab.name} and ${ENVIRONMENT_ID}`;
    const id = await projects.make({ name, ticket: 'PL-7', members: [me.handle!], tasks: [{ id: 'a', title, status: 'in_progress' }] });
    await projectList.open(id);

    const tab = projectList.tab(name);
    // The repo links once the settings are read.
    await expect(tab.getByTestId('projects.tab.name').getByRole('link', { name: 'pvginkel/Example' })).toBeVisible();
    await expect(tab.getByTestId('projects.tab.ticket')).toHaveText('PL-7');
    await expect(tab.getByTestId('projects.tab.ticket').getByRole('link')).toHaveCount(0);
    await expect(tab.getByTestId('projects.tab.status')).toHaveText(title);
    await expect(tab.getByTestId('projects.tab.status').getByRole('link')).toHaveCount(0);
  });
});
