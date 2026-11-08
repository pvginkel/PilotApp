/**
 * A text field's window, run in the page: its scroll, its height, its line, how far its top lies
 * from the nearest line's top, and its half leading, the most that cuts no text there.
 */
export function windowOf(field: HTMLTextAreaElement) {
  const style = getComputedStyle(field);
  const line = parseFloat(style.lineHeight);
  const into = field.scrollTop % line;
  return {
    top: field.scrollTop,
    height: field.clientHeight,
    line,
    cut: Math.min(into, line - into),
    leading: (line - parseFloat(style.fontSize)) / 2,
  };
}
