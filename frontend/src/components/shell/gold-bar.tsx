/**
 * The gold bar (F125, F135.7; UC *The gold bar*): what holds all work, a condition each — the
 * controller unreachable, the week's usage halt, the five-hour one. Off a phone a badge per
 * condition in the top bar, after Pilot's name, its full line its title; the week's halt's, which
 * carries its overrule (F135.2), a button opening a popover that holds its line and the overrule,
 * so that a stray click on the top bar spends no quota. On a phone a line per condition across the
 * window under the top bar, the drawer opening under it, the overrule on the halt's line. Each
 * stands while its condition holds and goes when it ends; nothing dismisses it. The time a
 * condition began carries its date once that is an earlier day than the viewer's today.
 */

import { ChevronDown } from 'lucide-react';
import { Popover } from '@/components/shared/popover';
import { Time } from '@/components/shared/time';
import type { Condition } from '@/hooks/use-conditions';
import { useToast } from '@/hooks/use-toast';
import { useToday } from '@/hooks/use-today';
import { usePostQuotaOverrules } from '@/lib/api/generated/hooks';
import { trackFormError, trackFormSubmit, trackFormSuccess } from '@/lib/test/form-instrumentation';
import { conditionLine, overruleWords } from '@/lib/utils/status-labels';
import { clockFormat, formatTime } from '@/lib/utils/time-format';

type OverruleKind = NonNullable<Condition['offer']>;

interface GoldProps {
  conditions: Condition[];
}

/** The top bar's badges; the phone has the lines instead. */
export function GoldBadges({ conditions }: GoldProps) {
  const today = useToday();
  return (
    // A live region from the first render on, so that a badge coming in is announced.
    <div className="gold-badges" role="status" aria-label="What holds all work" data-testid="shell.gold-badges">
      {conditions.map((condition) => (
        <GoldBadge key={condition.code} condition={condition} today={today} />
      ))}
    </div>
  );
}

function GoldBadge({ condition, today }: { condition: Condition; today: string }) {
  const { title, detail, badge, icon: Icon } = conditionLine(condition, today);
  const since = formatTime(condition.since, clockFormat(condition.since, today));
  const words = (
    <>
      <Icon className="icon" aria-hidden="true" />
      {badge} since {since}
    </>
  );
  if (condition.offer === null) {
    return (
      <span
        className="gold-badge"
        title={`${title} since ${since}. ${detail}`}
        data-condition={condition.code}
        data-testid="shell.gold-badges.badge"
      >
        {words}
      </span>
    );
  }
  return (
    <Popover
      label={badge}
      anchorClassName="gold-badge-wrap"
      className="gold-pop"
      testId="shell.gold-badges.popover"
      trigger={({ open, toggle }) => (
        <button
          type="button"
          className="gold-badge"
          aria-haspopup="dialog"
          aria-expanded={open}
          onClick={toggle}
          data-condition={condition.code}
          data-testid="shell.gold-badges.badge"
        >
          {words}
          <ChevronDown className="icon chev" aria-hidden="true" />
        </button>
      )}
    >
      {(close) => <GoldLine condition={condition} today={today} testId="shell.gold-badges.popover.line" onOverrule={close} />}
    </Popover>
  );
}

/** The phone's lines, across the window under the top bar. */
export function GoldBar({ conditions }: GoldProps) {
  const today = useToday();
  return (
    // A live region from the first render on, so that a line coming in is announced.
    <div className="gold-bar" role="status" aria-label="What holds all work" data-testid="shell.gold-bar">
      {conditions.map((condition) => (
        <GoldLine key={condition.code} condition={condition} today={today} testId="shell.gold-bar.line" />
      ))}
    </div>
  );
}

interface GoldLineProps {
  condition: Condition;
  today: string;
  testId: string;
  /** Called as its overrule is made. */
  onOverrule?: () => void;
}

/** A condition's line, with the overrule it offers: on the phone's bar, and in the week's halt's popover. */
function GoldLine({ condition, today, testId, onOverrule }: GoldLineProps) {
  const { title, detail, icon: Icon } = conditionLine(condition, today);
  return (
    <div className="gold-line" data-condition={condition.code} data-testid={testId}>
      <Icon className="icon" aria-hidden="true" />
      <div className="gold-body">
        <p data-testid="shell.gold-line.text">
          <strong>
            {title} since <Time at={condition.since} format={clockFormat(condition.since, today)} />.
          </strong>{' '}
          {detail}
        </p>
        {condition.offer !== null && (
          <div className="gold-actions">
            <OverruleButton kind={condition.offer} target={condition.target} onMade={onOverrule} />
          </div>
        )}
      </div>
    </div>
  );
}

const FORM = 'shell.overrule';

interface OverruleButtonProps {
  kind: OverruleKind;
  /** The allowance's target, a fraction. */
  target: number | null;
  onMade?: () => void;
}

/** The overrule the week's halt offers now (F135.2), one at a time; its toast says what it did. */
function OverruleButton({ kind, target, onMade }: OverruleButtonProps) {
  const overrule = usePostQuotaOverrules();
  const { showSuccess } = useToast();
  const { label, does } = overruleWords(kind, target);
  const make = () => {
    trackFormSubmit(FORM, { kind });
    // The halt's lifting can take the button off the screen before the answer comes: the toast
    // follows the request, not the button. The query client toasts a refusal (UI-2).
    void overrule.mutateAsync({ body: { kind } }).then(
      (made) => {
        trackFormSuccess(FORM, { kind });
        showSuccess(overruleWords(made.kind, made.target).does);
      },
      () => trackFormError(FORM, { kind }),
    );
    onMade?.();
  };
  return (
    <button
      type="button"
      className="gold-btn"
      title={does}
      disabled={overrule.isPending}
      onClick={make}
      data-testid="shell.gold-line.overrule"
    >
      {label}
    </button>
  );
}
