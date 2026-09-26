import { Thread } from "@/components/inbox/Thread";

export default async function ConversationPage({
  params,
}: {
  params: Promise<{ tenant: string; conversationId: string }>;
}) {
  const { tenant, conversationId } = await params;
  return <Thread tenant={tenant} conversationId={conversationId} />;
}
