"use client";

import { useState, type ReactNode } from "react";
import { useMe } from "@/lib/api/hooks";
import { useT } from "@/lib/i18n-client";
import { Avatar } from "./Avatar";
import { Icon } from "./Icon";
import { Modal } from "./Modal";

/**
 * Who is signed in, and what is theirs to change: the language, the
 * workspace, whether they are taking chats, the way out ([11] § 4). What goes
 * inside is the shell's to say — some of it is drawn on the server, which this
 * component may be handed and may not import.
 */
export function AccountMenu({ children }: { children: ReactNode }) {
  const t = useT();
  const me = useMe();
  const [open, setOpen] = useState(false);
  const name = me.data?.user.name;
  return (
    <>
      <button
        type="button"
        aria-haspopup="dialog"
        aria-label={t("account.title")}
        onClick={() => setOpen(true)}
        className="icon-btn"
      >
        <Avatar name={name} />
      </button>
      {open && (
        <Modal label={t("account.title")} onClose={() => setOpen(false)}>
          <div className="flex items-center gap-3">
            <Avatar name={name} />
            <h2 dir="auto" className="min-w-0 flex-1 truncate text-base font-semibold">
              {name}
            </h2>
            <button
              type="button"
              aria-label={t("common.close")}
              onClick={() => setOpen(false)}
              className="icon-btn"
            >
              <Icon name="close" />
            </button>
          </div>
          <div className="mt-4 flex flex-col gap-4">{children}</div>
        </Modal>
      )}
    </>
  );
}
