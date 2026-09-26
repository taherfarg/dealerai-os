"use client";

import { StageEditor } from "@/components/settings/StageEditor";
import { usePipelines } from "@/lib/api/hooks";
import { useT } from "@/lib/i18n-client";

/** Every board, each reshaped on its own (08-screens § 13). */
export default function PipelineSettingsPage() {
  const t = useT();
  const pipelines = usePipelines();
  return (
    <div className="flex flex-col gap-4">
      <h1 className="text-lg font-semibold">{t("settings.pipelines")}</h1>
      <p className="text-muted text-xs">{t("pipelines.rules")}</p>
      {(pipelines.data ?? []).map((pipeline) => (
        <StageEditor key={pipeline.id} pipeline={pipeline} />
      ))}
    </div>
  );
}
