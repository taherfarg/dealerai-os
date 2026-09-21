import { ConversationList } from "@/components/inbox/ConversationList";

/**
 * Two panes on a desktop, one on a phone.
 *
 * On a phone the list and the thread are separate screens: the list hides once
 * a conversation is open, which is what the back button in the thread header
 * undoes.
 *
 * `h-full` rather than a height in rem: the composer has to sit above the
 * phone's bottom bar, and how much room that leaves is the layout's business,
 * not a number guessed here.
 */
export default function InboxLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <div className="group grid h-full grid-cols-1 lg:grid-cols-[360px_1fr] lg:gap-0">
      <aside className="min-h-0 border-black/5 group-has-[[data-thread]]:hidden lg:block lg:border-e lg:group-has-[[data-thread]]:block dark:border-white/10">
        <ConversationList />
      </aside>
      <section className="min-h-0">{children}</section>
    </div>
  );
}
