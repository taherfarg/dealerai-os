/**
 * jsdom has the <dialog> element and none of its behaviour. What a component
 * test needs of it is that it opens and closes. Where focus goes, what Tab
 * reaches and what Escape does are the browser's own, and are checked in one
 * (docs/sales/plans/s7-pilot-readiness.md, Part C).
 */
if (typeof HTMLDialogElement !== "undefined" && !HTMLDialogElement.prototype.showModal) {
  HTMLDialogElement.prototype.showModal = function showModal(this: HTMLDialogElement) {
    this.setAttribute("open", "");
  };
  HTMLDialogElement.prototype.close = function close(this: HTMLDialogElement) {
    this.removeAttribute("open");
    this.dispatchEvent(new Event("close"));
  };
}
