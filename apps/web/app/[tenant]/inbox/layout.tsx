import { ConversationList } from "@/components/inbox/ConversationList";

/**
 * Two panes on a desktop, one on a phone.
 *
 * On a phone the list and the thread are separate screens: `has-[[data-thread]]`
 * hides the list once a conversation is open, which is what the back button in
 * the thread header undoes.
 */
export default function InboxLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="grid h-[calc(100dvh-8rem)] grid-cols-1 lg:grid-cols-[360px_1fr] lg:gap-0">
      <aside className="min-h-0 border-black/5 lg:border-e dark:border-white/10">
        <ConversationList />
      </aside>
      <section className="min-h-0">{children}</section>
    </div>
  );
}
