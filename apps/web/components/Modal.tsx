"use client";

import { useId, useLayoutEffect, useRef, type ReactNode } from "react";

const SHAPE = {
  // A box in the middle, which scrolls inside itself when a phone's keyboard
  // leaves it less room than it needs.
  dialog:
    "m-auto max-h-[calc(100dvh-2rem)] w-[min(32rem,calc(100vw-2rem))] overflow-y-auto rounded-lg border",
  // The whole of a phone's screen; a column at the end of a wider one.
  sheet: "my-0 ms-auto me-0 h-dvh max-h-none w-full max-w-none overflow-y-auto border-s sm:w-96",
} as const;

/**
 * A modal, on the platform's own: `<dialog>` and `showModal()` move focus in,
 * keep Tab inside, close on Escape and give focus back to whatever opened it
 * ([07] § 10) — none of which a `div` with `role="dialog"` does.
 *
 * Whether it is open is its owner's to say: it is on screen while it is
 * rendered, and asks to be closed through `onClose`.
 */
export function Modal({
  title,
  label,
  variant = "dialog",
  onClose,
  children,
}: {
  /** Shown as the heading, which is also the dialog's name. */
  title?: ReactNode;
  /** The name, when what is inside brings a heading of its own. */
  label?: string;
  variant?: keyof typeof SHAPE;
  onClose: () => void;
  children: ReactNode;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  const heading = useId();

  // A layout effect, for its cleanup: that runs while the dialog is still on
  // the page, and closing it there is what hands focus back. An effect's would
  // run after React had removed it, and focus would be left on nothing.
  useLayoutEffect(() => {
    const dialog = ref.current;
    if (!dialog || dialog.open) return;
    dialog.showModal();
    return () => dialog.close();
  }, []);

  return (
    <dialog
      ref={ref}
      aria-labelledby={title ? heading : undefined}
      aria-label={title ? undefined : label}
      onCancel={(event) => {
        event.preventDefault(); // React owns whether it is open
        onClose();
      }}
      onClick={(event) => {
        // The backdrop belongs to the dialog element; everything a person can
        // see is inside the padded box below, so only a press outside lands here.
        if (event.target === ref.current) onClose();
      }}
      // overscroll-contain: reaching the end of the dialog does not start
      // scrolling the page underneath it.
      className={`bg-background text-foreground border-border overscroll-contain p-0 shadow-lg backdrop:bg-black/40 ${SHAPE[variant]}`}
    >
      <div className={variant === "sheet" ? "min-h-full" : "p-4"}>
        {title && (
          <h2 id={heading} className="text-base font-semibold">
            {title}
          </h2>
        )}
        {children}
      </div>
    </dialog>
  );
}
