/**
 * The side column (F1): the project list, the person's projects first, then Other projects and
 * Finished; or the archived projects, opened from the list's menu, with a back arrow (D012).
 */

import { useState } from 'react';
import { useParams } from '@tanstack/react-router';
import { Archive, ArrowLeft, ChevronDown, ChevronRight, Ellipsis } from 'lucide-react';
import { ProjectTab } from '@/components/projects/project-tab';
import { Menu, MenuItem } from '@/components/shared/menu';
import { groupProjects, useArchivedProjects, useProjectList, type ProjectTab as Project } from '@/hooks/use-projects';
import { rememberInBrowser, useBrowserState, type Group } from '@/lib/browser-state';

export function ProjectColumn() {
  const [archived, setArchived] = useState(false);
  return archived ? <ArchivedList onBack={() => setArchived(false)} /> : <ProjectList onArchived={() => setArchived(true)} />;
}

const GROUP_NAMES: Record<Group, string> = { others: 'Other projects', finished: 'Finished' };

function ProjectList({ onArchived }: { onArchived: () => void }) {
  const { data } = useProjectList();
  const onScreen = useParams({ strict: false, select: (params) => params.projectId });
  const { chevrons } = useBrowserState();
  // A group the project on screen is in stands open by itself; closed by the person, it stays
  // closed until another project comes on screen.
  const [closed, setClosed] = useState<{ project: string | undefined; groups: Partial<Record<Group, true>> }>({
    project: onScreen,
    groups: {},
  });
  if (closed.project !== onScreen) setClosed({ project: onScreen, groups: {} });

  const groups = groupProjects(data?.projects ?? []);
  const holdsOnScreen = (group: Group) => groups[group].some((project) => project.id === onScreen);
  const isOpen = (group: Group) => chevrons[group] || (holdsOnScreen(group) && !closed.groups[group]);
  const toggle = (group: Group) => {
    const open = isOpen(group);
    rememberInBrowser({ chevrons: { ...chevrons, [group]: !open } });
    if (open && holdsOnScreen(group)) setClosed({ project: onScreen, groups: { ...closed.groups, [group]: true } });
  };

  return (
    <>
      <div className="tabs-head" data-testid="projects.head">
        Projects
        <Menu
          label="The project list's menu"
          testId="projects.menu"
          trigger={({ open, toggle: toggleMenu }) => (
            <button
              type="button"
              className="btn btn-ghost btn-sm btn-icon"
              title="More"
              aria-label="More"
              aria-haspopup="menu"
              aria-expanded={open}
              onClick={toggleMenu}
              data-testid="projects.menu.button"
            >
              <Ellipsis className="icon" aria-hidden="true" />
            </button>
          )}
        >
          <MenuItem icon={Archive} onSelect={onArchived} testId="projects.menu.archived">
            Archived
          </MenuItem>
        </Menu>
      </div>
      <div data-testid="projects.mine">
        {groups.mine.map((project) => (
          <ProjectTab key={project.id} project={project} />
        ))}
      </div>
      {(['others', 'finished'] as const).map((group) => (
        <TabsGroup key={group} group={group} projects={groups[group]} open={isOpen(group)} onToggle={() => toggle(group)} />
      ))}
    </>
  );
}

interface TabsGroupProps {
  group: Group;
  projects: Project[];
  open: boolean;
  onToggle: () => void;
}

function TabsGroup({ group, projects, open, onToggle }: TabsGroupProps) {
  if (projects.length === 0) return null;
  const Chevron = open ? ChevronDown : ChevronRight;
  return (
    <div data-testid={`projects.group.${group}`}>
      <button
        type="button"
        className="tabs-group"
        aria-expanded={open}
        onClick={onToggle}
        data-testid={`projects.group.${group}.toggle`}
      >
        <Chevron className="icon" aria-hidden="true" />
        {GROUP_NAMES[group]}
        <span className="ptab-count" data-testid={`projects.group.${group}.count`}>
          {projects.length}
        </span>
      </button>
      {open && projects.map((project) => <ProjectTab key={project.id} project={project} />)}
    </div>
  );
}

function ArchivedList({ onBack }: { onBack: () => void }) {
  const { data } = useArchivedProjects();
  return (
    <div data-testid="projects.archived">
      <div className="tabs-head archived">
        <button
          type="button"
          className="btn btn-ghost btn-sm btn-icon"
          title="Back to the projects"
          aria-label="Back to the projects"
          onClick={onBack}
          data-testid="projects.archived.back"
        >
          <ArrowLeft className="icon" aria-hidden="true" />
        </button>
        Archived
      </div>
      {data?.projects.length === 0 && <p className="tabs-none">None yet</p>}
      {data?.projects.map((project) => <ProjectTab key={project.id} project={project} />)}
    </div>
  );
}
