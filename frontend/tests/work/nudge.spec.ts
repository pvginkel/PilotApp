/**
 * A run halted or paused at its turn's end, and its nudge (F135.3, F135.6, F141.3): a work item whose
 * turn ends well while the halt file is written for it — the week's halt, the suite's backends' a
 * cooperative stop (tests/support/backend-env-extensions.ts), or its project's pause — is not done. It
 * stays open, its line saying what holds it as a held start's does, "Halted at the week’s limit" or
 * "Paused", waiting on nobody, its tile and its session log's cue standing still, and its halt
 * file goes at its turn's end; its session log says so too, under the turn's end. Once nothing holds it, the nudge carries the same run on, and it is done at
 * that turn's end. It offers Stop, which leaves it stopped, not done, its nudge owed no more, so
 * that nothing carries it on but its Resume (W8).
 */

import { rawTurn, type Controller } from "../support/controller";
import { test, expect } from "../support/fixtures";
import { makeUnique } from "../support/helpers";
import type { People } from "../support/people";
import type { Projects } from "../support/projects";

const HALT_FILE = "/work/.quota-limit-halt-requested";

interface Fixtures {
  people: People;
  projects: Projects;
  controller: Controller;
}

/**
 * A project, signed in as its member, and a work item running in it with its environment, its turn's
 * lines played: its conversation, which the nudge goes on.
 */
async function running({
  people,
  projects,
  controller,
}: Fixtures): Promise<{
  name: string;
  project: string;
  work: string;
  environment: string;
}> {
  const me = await people.signIn();
  const name = makeUnique("Nudge");
  const project = await projects.make({ name, members: [me.handle!] });
  const work = await projects.startWork(project, {
    title: "Surveying the stylesheets",
    brief: "Survey the stylesheets.",
    cwd: "/work/Example",
  });
  await expect
    .poll(async () => (await projects.work(project, work)).state)
    .toBe("running");
  const { id: environment } = await projects.environment(project, work);
  await controller.play(environment, "claude-1", rawTurn("turn_text"));
  return { name, project, work, environment };
}

test.describe("A run halted at its turn’s end", () => {
  test("stays open under the week’s halt, its line saying so, waiting on nobody, and its nudge carries it on once a reading lifts the halt", async ({
    people,
    projects,
    controller,
    timeline,
    sessionLog,
    projectList,
    deploymentSse,
    page,
  }) => {
    const { name, project, work, environment } = await running({
      people,
      projects,
      controller,
    });
    await timeline.open(project);
    await deploymentSse.ensureConnected();
    const item = timeline.item(work);

    await controller.usage({ seven_day: 0.92, five_hour: 0.1 });
    await expect
      .poll(() => controller.fileText(environment, HALT_FILE))
      .toBe("");
    await controller.finish(
      environment,
      "claude-1",
      "success",
      "Surveyed half of them.",
    );

    await expect(item.work.line).toHaveAttribute("data-state", "idle");
    await expect(item.work.cue).toHaveText("Halted at the week’s limit");
    // Its nudge owed, nothing moves: no pulse, no dots (W2).
    await expect(item.work.live).toHaveCount(0);
    await expect(item.work.dots).toHaveCount(0);
    await expect(item.root).toHaveAttribute("data-state", "open");
    // W8: Stop is offered, in the head; nothing in the row.
    await expect(item.work.stop).toBeVisible();
    await expect(item.work.resume).toHaveCount(0);
    await expect(item.work.row).toHaveCount(0);
    await expect(projectList.badge(name)).toHaveCount(0);
    await expect
      .poll(() => controller.fileText(environment, HALT_FILE))
      .toBeNull();
    await item.work.sessionLog.click();
    await expect(sessionLog.tail).toHaveText(/^The turn ended · \d\d:\d\d$/);
    await expect(sessionLog.cue).toHaveText("Halted at the week’s limit");
    await expect(sessionLog.dots).toHaveCount(0);
    await page.keyboard.press("Escape");

    await controller.usage({ seven_day: 0.5, five_hour: 0.1 });

    await expect(item.work.running).toBeVisible();
    expect((await projects.item(project, work)).done).toBeNull();
    await controller.finish(environment, "claude-1");
    await expect
      .poll(async () => (await projects.item(project, work)).done?.cause)
      .toBe("turn_ended");
    await expect(item.root).toHaveAttribute("data-state", "done");
  });

  test("offers Stop, which leaves it stopped, not done, its nudge owed no more: the halt lifted, the nudge carries another on and not this one, and its Resume does", async ({
    people,
    projects,
    controller,
    timeline,
    deploymentSse,
  }) => {
    const { project, work, environment } = await running({
      people,
      projects,
      controller,
    });
    const other = await projects.startWork(project, {
      title: "Surveying the scripts",
      brief: "Survey the scripts.",
      cwd: "/work/Example",
    });
    await expect
      .poll(async () => (await projects.work(project, other)).state)
      .toBe("running");
    const { id: otherEnvironment } = await projects.environment(project, other);
    await controller.play(otherEnvironment, "claude-1", rawTurn("turn_text"));
    await timeline.open(project);
    await deploymentSse.ensureConnected();
    const item = timeline.item(work).work;
    const carried = timeline.item(other).work;

    await controller.usage({ seven_day: 0.92, five_hour: 0.1 });
    for (const each of [environment, otherEnvironment]) {
      await expect.poll(() => controller.fileText(each, HALT_FILE)).toBe("");
      await controller.finish(each, "claude-1", "success", "Surveyed half.");
    }
    await expect(item.cue).toHaveText("Halted at the week’s limit");
    await expect(carried.cue).toHaveText("Halted at the week’s limit");

    await item.stop.click();
    await item.stopConfirm.yes.click();
    await expect(item.line).toHaveAttribute("data-state", "stopped");
    await expect(item.line).toHaveText(/^Stopped · \d\d:\d\d$/);
    await expect(item.resume).toBeVisible();
    await expect(item.stop).toHaveCount(0);
    const stopped = await projects.work(project, work);
    expect(stopped.nudge_owed).toBe(false);
    expect((await projects.item(project, work)).done).toBeNull();

    // The nudges owed go out in one run: the other is carried on, and this one stays stopped.
    await controller.usage({ seven_day: 0.5, five_hour: 0.1 });
    await expect(carried.running).toBeVisible();
    expect((await projects.work(project, work)).state).toBe("stopped");
    await expect(item.line).toHaveAttribute("data-state", "stopped");

    await item.resume.click();
    await expect(item.running).toBeVisible();
  });

  test("stays open under its project’s pause, its line “Paused”, and is nudged at the resume", async ({
    people,
    projects,
    controller,
    timeline,
    deploymentSse,
  }) => {
    const { project, work, environment } = await running({
      people,
      projects,
      controller,
    });
    await timeline.open(project);
    await deploymentSse.ensureConnected();
    const item = timeline.item(work).work;

    await projects.transition(project, "paused");
    await expect
      .poll(() => controller.fileText(environment, HALT_FILE))
      .toBe("");
    await controller.finish(environment, "claude-1");

    await expect(item.line).toHaveAttribute("data-state", "idle");
    await expect(item.cue).toHaveText("Paused");

    await projects.transition(project, "resumed");

    await expect(item.running).toBeVisible();
    expect((await projects.item(project, work)).done).toBeNull();
  });
});
