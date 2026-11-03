/** Scrolls the body so that an element drawn in it stands at its top, its scroll margin above it. */
export function scrollToIn(body: HTMLElement, element: HTMLElement, behavior: ScrollBehavior) {
  const top =
    element.getBoundingClientRect().top -
    body.getBoundingClientRect().top -
    body.clientTop +
    body.scrollTop -
    parseFloat(getComputedStyle(element).scrollMarginTop);
  body.scrollTo({ top, behavior });
}
