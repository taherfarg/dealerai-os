import { CreateWorkspace } from "@/components/auth/CreateWorkspace";

/** Where the root sends somebody who belongs to no workspace. A static
 *  segment, so it wins over `[tenant]`. */
export default function OnboardingPage() {
  return <CreateWorkspace />;
}
