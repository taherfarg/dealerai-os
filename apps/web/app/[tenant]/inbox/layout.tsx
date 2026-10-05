import { ConversationList } from "@/components/inbox/ConversationList";

/**
 * Two panels on a desk, one screen at a time on a phone ([11] § 5.1).
 *
 * On a phone the list and the thread are separate screens: the list hides once
 * a conversation is open, which is what the back button in the thread header
 * undoes.
 *
 * The inbox is the one page that fits the window exactly, so that the composer
 * sits at its foot: it takes back the padding the shell gives every page, and
 * its height is the window's, less the row the shell says it keeps at the top
 * (`--shell-top`, in components/Shell.tsx).
 */
export default function InboxLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    // One row that is the whole height: whichever of the two is on screen
    // fills it, and scrolls inside itself.
    <div className="group -mx-4 -mt-4 -mb-28 grid h-[calc(100dvh-var(--shell-top))] grid-cols-1 grid-rows-[minmax(0,1fr)] md:-m-8 lg:grid-cols-[23.25rem_1fr]">
      {/* A div, not an aside: the list is the page, not something beside it —
          and the shell already has the page's one complementary landmark. */}
      <div className="bg-background border-border min-h-0 group-has-[[data-thread]]:hidden lg:block lg:border-e lg:group-has-[[data-thread]]:block">
        <ConversationList />
      </div>
      <section className="bg-ground min-h-0">{children}</section>
    </div>
  );
}
