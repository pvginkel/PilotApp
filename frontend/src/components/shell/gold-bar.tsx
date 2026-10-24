/**
 * The gold bar (F125; UC *The gold bar*): what holds all work, a line per condition, over the
 * project list, and across the window under the top bar below the breakpoint, where the list is a
 * drawer. A line stands while its condition holds and goes when it ends; nothing dismisses it.
 */

import { Time } from '@/components/shared/time';
import { useConditions } from '@/hooks/use-conditions';
import { conditionLine } from '@/lib/utils/status-labels';

export function GoldBar() {
  const conditions = useConditions();
  return (
    // A live region from the first render on, so that a line coming in is announced.
    <div className="gold-bar" role="status" aria-label="What holds all work" data-testid="shell.gold-bar">
      {conditions.map((condition) => {
        const { title, detail, icon: Icon } = conditionLine(condition.code);
        return (
          <div key={condition.code} className="gold-line" data-condition={condition.code} data-testid="shell.gold-bar.line">
            <Icon className="icon" aria-hidden="true" />
            <p>
              <strong>
                {title} since <Time at={condition.since} format="clock" />.
              </strong>{' '}
              {detail}
            </p>
          </div>
        );
      })}
    </div>
  );
}
