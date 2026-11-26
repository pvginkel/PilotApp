/**
 * The dashboard's screen (F160), a module of its own, which the shell loads at the dashboard's
 * first opening (F160.2): a page that never opens it never loads it. Out of sight it lies under
 * the Projects screen, in its box, out of the flow, its visibility off and inert.
 */

export function DashboardScreen({ shown }: { shown: boolean }) {
  return <section className={shown ? 'dash' : 'dash away'} inert={!shown} aria-label="Dashboard" data-testid="dashboard" />;
}
