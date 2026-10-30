/**
 * The gold bar (F125, F135.7; UC *The gold bar*): what holds all work, a condition each — the
 * controller unreachable, the week's usage halt, the five-hour one. Off a phone a
 * badge per condition in the top bar, after Pilot's name, its full line its title; on a phone a
 * line per condition across the window under the top bar, the drawer opening under it. Each stands
 * while its condition holds and goes when it ends; nothing dismisses it. The time a condition began
 * carries its date once that is an earlier day than the viewer's today.
 */

import { Time } from '@/components/shared/time';
import type { Condition } from '@/hooks/use-conditions';
import { useToday } from '@/hooks/use-today';
import { conditionLine } from '@/lib/utils/status-labels';
import { clockFormat, formatTime } from '@/lib/utils/time-format';

interface GoldProps {
  conditions: Condition[];
}

/** The top bar's badges; the phone has the lines instead. */
export function GoldBadges({ conditions }: GoldProps) {
  const today = useToday();
  return (
    // A live region from the first render on, so that a badge coming in is announced.
    <div className="gold-badges" role="status" aria-label="What holds all work" data-testid="shell.gold-badges">
      {conditions.map((condition) => {
        const { title, detail, badge, icon: Icon } = conditionLine(condition, today);
        const since = formatTime(condition.since, clockFormat(condition.since, today));
        return (
          <span
            key={condition.code}
            className="gold-badge"
            title={`${title} since ${since}. ${detail}`}
            data-condition={condition.code}
            data-testid="shell.gold-badges.badge"
          >
            <Icon className="icon" aria-hidden="true" />
            {badge} since {since}
          </span>
        );
      })}
    </div>
  );
}

/** The phone's lines, across the window under the top bar. */
export function GoldBar({ conditions }: GoldProps) {
  const today = useToday();
  return (
    // A live region from the first render on, so that a line coming in is announced.
    <div className="gold-bar" role="status" aria-label="What holds all work" data-testid="shell.gold-bar">
      {conditions.map((condition) => {
        const { title, detail, icon: Icon } = conditionLine(condition, today);
        return (
          <div key={condition.code} className="gold-line" data-condition={condition.code} data-testid="shell.gold-bar.line">
            <Icon className="icon" aria-hidden="true" />
            <p>
              <strong>
                {title} since <Time at={condition.since} format={clockFormat(condition.since, today)} />.
              </strong>{' '}
              {detail}
            </p>
          </div>
        );
      })}
    </div>
  );
}
