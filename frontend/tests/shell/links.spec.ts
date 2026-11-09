/**
 * Links in text (F91, F93): a ticket id by the deployment's pattern and URL template, a repo
 * written pvginkel/Name to GitHub, an environment by its id's form or by a name of the record's to
 * KubeCoder's Open; in the colour of the text around them, underlined under the mouse; unlinked
 * while a setting is unset. A project's tab is the first text they show in: an <a> itself, so each
 * is a span that opens it, and its ticket ids, as a step button's name's, are plain text (the step
 * button's in tests/projects/project-head.spec.ts).
 *
 * The ticket and KubeCoder addresses are the backend's own, so a link opened in a popup loads.
 */

import { test, expect } from '../support/fixtures';
import { makeUnique, makeUniqueToken } from '../support/helpers';
import { projectAddress } from '../support/projects';

const ENVIRONMENT_ID = 'pvginkel-example-1a2b3c';

test.describe('Links in text', () => {
  test('a repo and an environment link in a tab, each a span that opens it, and a ticket id is plain text there', async ({
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
    const status = tab.getByTestId('projects.tab.status');
    const environment = status.getByRole('link', { name: lab.name });
    const byId = status.getByRole('link', { name: ENVIRONMENT_ID });
    const kubecoder = `${backendUrl}/kubecoder/environments`;
    await expect(tab.getByTestId('projects.tab.name').getByRole('link', { name: 'pvginkel/Example' })).toHaveAttribute(
      'data-href',
      'https://github.com/pvginkel/Example',
    );
    await expect(environment).toHaveAttribute('data-href', `${kubecoder}/${lab.id}/ssh/open`);
    await expect(byId).toHaveAttribute('data-href', `${kubecoder}/${ENVIRONMENT_ID}/ssh/open`);
    await expect(status).toHaveText(title);
    await expect(tab.getByTestId('projects.tab.ticket')).toHaveText('PL-7');
    await expect(tab.getByTestId('projects.tab.ticket').getByRole('link')).toHaveCount(0);

    // A click opens the environment, and not the tab around it.
    const clicked = page.waitForEvent('popup');
    await environment.click();
    expect((await clicked).url()).toBe(`${kubecoder}/${lab.id}/ssh/open`);
    await expect(page).toHaveURL(projectAddress(onScreen));

    // Enter on a focused one opens it too.
    await byId.focus();
    const entered = page.waitForEvent('popup');
    await page.keyboard.press('Enter');
    expect((await entered).url()).toBe(`${kubecoder}/${ENVIRONMENT_ID}/ssh/open`);
    await expect(page).toHaveURL(projectAddress(onScreen));
  });

  test('a ticket id is plain text in a tab, in its name, ticket and status line, a repo linking still', async ({
    backendUrl,
    people,
    projects,
    projectList,
    links,
  }) => {
    await links.set({ ticket_url_template: `${backendUrl}/tickets/{id}` });
    const me = await people.signIn();
    const name = `${makeUnique('Port')} for PL-8`;
    const title = 'Close PL-9 on pvginkel/Example';
    const id = await projects.make({ name, ticket: 'PL-7', members: [me.handle!], tasks: [{ id: 'a', title, status: 'in_progress' }] });
    await projectList.open(id);

    const tab = projectList.tab(name);
    await expect(tab.getByTestId('projects.tab.name')).toHaveText(name);
    await expect(tab.getByTestId('projects.tab.status')).toHaveText(title);
    // The repo still links; no ticket id does.
    await expect(tab.getByTestId('projects.tab.status').getByRole('link', { name: 'pvginkel/Example' })).toBeVisible();
    for (const part of ['name', 'ticket', 'status']) {
      await expect(tab.getByTestId(`projects.tab.${part}`).getByRole('link', { name: /PL-/ })).toHaveCount(0);
    }
  });

  test('of two environments, one named as the other plus a hyphen suffix, the longer name links to its own', async ({
    backendUrl,
    people,
    projects,
    projectList,
    links,
  }) => {
    await links.set({ environment_link_base_url: `${backendUrl}/kubecoder` });
    const lab = { id: makeUnique('env'), name: `${makeUnique('Lab')}-1` };
    const labTwo = { id: makeUnique('env'), name: `${lab.name}-2` };
    await links.environment(lab.id, lab.name);
    await links.environment(labTwo.id, labTwo.name);
    const me = await people.signIn();
    const name = makeUnique('Suffixed');
    const id = await projects.make({ name, members: [me.handle!], tasks: [{ id: 'a', title: `Restart ${labTwo.name}`, status: 'in_progress' }] });
    await projectList.open(id);

    const status = projectList.tab(name).getByTestId('projects.tab.status');
    await expect(status.getByRole('link')).toHaveCount(1);
    await expect(status.getByRole('link', { name: labTwo.name, exact: true })).toHaveAttribute(
      'data-href',
      `${backendUrl}/kubecoder/environments/${labTwo.id}/ssh/open`,
    );
  });

  test('a link has the colour of the text around it and underlines under the mouse', async ({
    people,
    projects,
    projectList,
    links,
  }) => {
    await links.set({});
    const me = await people.signIn();
    const name = `${makeUnique('Coloured')} on pvginkel/Example`;
    const id = await projects.make({ name, members: [me.handle!] });
    await projectList.open(id);

    const around = projectList.tab(name).getByTestId('projects.tab.name');
    const repo = around.getByRole('link', { name: 'pvginkel/Example' });
    await expect(repo).toBeVisible();
    const style = (property: string) =>
      repo.evaluate((element, name) => getComputedStyle(element).getPropertyValue(name), property);
    expect(await style('color')).toBe(await around.evaluate((element) => getComputedStyle(element).color));
    expect(await style('text-decoration-line')).toBe('none');
    await repo.hover();
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
