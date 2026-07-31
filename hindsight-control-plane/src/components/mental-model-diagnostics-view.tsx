"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import {
  client,
  MentalModel,
  MentalModelDryRunRefreshResult,
  MentalModelRefreshTrace,
  ModeFallbackReason,
  RefreshOutcome,
} from "@/lib/api";
import { useBank } from "@/lib/bank-context";
import { Button } from "@/components/ui/button";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { AlertTriangle, FlaskConical, Loader2 } from "lucide-react";
import { formatAbsoluteDateTime as formatDateTime } from "@/lib/relative-time";

/** Override applied to the dry run. "stored" previews the model as configured. */
type ModeChoice = "stored" | "full" | "delta";

function SectionCard({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="rounded-lg border border-border overflow-hidden">
      <div className="px-3 py-1.5 bg-muted/50 border-b border-border text-xs font-semibold uppercase tracking-wide text-muted-foreground">
        {title}
      </div>
      <div className="p-3 text-sm space-y-1.5">{children}</div>
    </div>
  );
}

function Row({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="flex items-baseline gap-2">
      <span className="text-xs text-muted-foreground min-w-[7.5rem] shrink-0">{label}</span>
      <span className="font-mono text-[13px] break-all">{value}</span>
    </div>
  );
}

function CountList({ counts, emptyLabel }: { counts: Record<string, number>; emptyLabel: string }) {
  const entries = Object.entries(counts ?? {});
  if (entries.length === 0)
    return <span className="text-muted-foreground italic text-[13px]">{emptyLabel}</span>;
  return (
    <span className="font-mono text-[13px]">
      {entries.map(([type, count]) => `${type}: ${count}`).join(", ")}
    </span>
  );
}

/** Renders the unified diff the API returns, colouring hunks, additions and removals. */
function UnifiedDiff({ diff, emptyLabel }: { diff: string; emptyLabel: string }) {
  if (!diff.trim()) {
    return <p className="text-sm text-muted-foreground italic">{emptyLabel}</p>;
  }
  return (
    <div className="border border-border rounded-md overflow-x-auto text-[13px] font-mono">
      {diff.split("\n").map((line, idx) => {
        const isAdd = line.startsWith("+") && !line.startsWith("+++");
        const isDel = line.startsWith("-") && !line.startsWith("---");
        const isHunk = line.startsWith("@@");
        return (
          <div
            key={idx}
            className={[
              "px-3 py-0.5 whitespace-pre leading-5",
              isAdd ? "bg-green-500/10 text-green-700 dark:text-green-400" : "",
              isDel ? "bg-red-500/10 text-red-700 dark:text-red-400" : "",
              isHunk ? "bg-muted text-muted-foreground" : "",
            ]
              .filter(Boolean)
              .join(" ")}
          >
            {line || " "}
          </div>
        );
      })}
    </div>
  );
}

function TraceDetails({ trace }: { trace: MentalModelRefreshTrace }) {
  const t = useTranslations("mentalModelDiagnostics");
  return (
    <div className="space-y-3">
      <SectionCard title={t("scopeTitle")}>
        <Row
          label={t("scopeTags")}
          value={trace.scope?.tags?.length ? trace.scope.tags.join(", ") : t("scopeNone")}
        />
        <Row label={t("scopeTagsMatch")} value={trace.scope?.tags_match ?? "—"} />
        <Row
          label={t("scopeFactTypes")}
          value={
            trace.scope?.fact_types?.length ? trace.scope.fact_types.join(", ") : t("scopeAll")
          }
        />
        <Row
          label={t("scopeExcluded")}
          value={
            trace.scope?.exclude_mental_models
              ? t("scopeExcludedAll")
              : (trace.scope?.exclude_mental_model_ids?.join(", ") ?? "—")
          }
        />
      </SectionCard>

      <SectionCard title={t("windowTitle")}>
        <Row
          label={t("windowFrom")}
          value={
            trace.window?.created_after
              ? formatDateTime(trace.window.created_after)
              : t("windowUnbounded")
          }
        />
        <Row
          label={t("windowTo")}
          value={trace.window?.created_before ? formatDateTime(trace.window.created_before) : "—"}
        />
        <Row
          label={t("windowWatermark")}
          value={trace.window?.watermark ? formatDateTime(trace.window.watermark) : t("scopeNone")}
        />
      </SectionCard>

      <SectionCard title={t("factsTitle")}>
        <Row
          label={t("factsRetrieved")}
          value={<CountList counts={trace.facts?.retrieved ?? {}} emptyLabel={t("factsNone")} />}
        />
        <Row
          label={t("factsUsed")}
          value={<CountList counts={trace.facts?.used ?? {}} emptyLabel={t("factsNone")} />}
        />
      </SectionCard>

      {trace.tool_calls?.length > 0 && (
        <SectionCard title={t("traceToolCalls")}>
          {trace.tool_calls.map((tc, idx) => (
            <div key={idx} className="flex items-baseline gap-2 text-[13px]">
              <span className="font-mono font-semibold">{tc.tool}</span>
              <span className="text-muted-foreground">
                {t("traceResults", { count: tc.result_count ?? 0 })} &middot;{" "}
                {t("traceDuration", { ms: tc.duration_ms })}
              </span>
            </div>
          ))}
        </SectionCard>
      )}

      {trace.llm_calls?.length > 0 && (
        <SectionCard title={t("traceLlmCalls")}>
          {trace.llm_calls.map((lc, idx) => (
            <div key={idx} className="flex items-baseline gap-2 text-[13px]">
              <span className="font-mono font-semibold">{lc.scope}</span>
              <span className="text-muted-foreground">
                {t("traceDuration", { ms: lc.duration_ms })}
              </span>
            </div>
          ))}
        </SectionCard>
      )}

      {trace.delta_operations && (
        <SectionCard title={t("deltaOpsTitle")}>
          <Row
            label={t("deltaApplied")}
            value={String(trace.delta_operations.applied?.length ?? 0)}
          />
          <Row
            label={t("deltaSkipped")}
            value={String(trace.delta_operations.skipped?.length ?? 0)}
          />
        </SectionCard>
      )}
    </div>
  );
}

function WarningList({ warnings, title }: { warnings: string[]; title: string }) {
  if (!warnings?.length) return null;
  return (
    <div className="rounded-lg border border-amber-500/40 bg-amber-500/10 p-3 space-y-1.5">
      <div className="flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wide text-amber-700 dark:text-amber-400">
        <AlertTriangle className="w-3.5 h-3.5" />
        {title}
      </div>
      {warnings.map((w, idx) => (
        <p key={idx} className="text-sm text-amber-900 dark:text-amber-200">
          {w}
        </p>
      ))}
    </div>
  );
}

export function MentalModelDiagnosticsView({ mentalModel }: { mentalModel: MentalModel }) {
  const t = useTranslations("mentalModelDiagnostics");
  const { currentBank } = useBank();
  const [mode, setMode] = useState<ModeChoice>("stored");
  const [running, setRunning] = useState(false);
  const [result, setResult] = useState<MentalModelDryRunRefreshResult | null>(null);

  // Written by trigger.keep_trace on the model's last real refresh — visible
  // without spending any tokens, unlike a dry run.
  const storedTrace = mentalModel.reflect_response?.trace as MentalModelRefreshTrace | undefined;

  const handleRun = async () => {
    if (!currentBank) return;
    setRunning(true);
    try {
      const data = await client.dryRunRefreshMentalModel(
        currentBank,
        mentalModel.id,
        mode === "stored" ? {} : { mode }
      );
      setResult(data);
    } catch (err) {
      console.error("Error running mental model dry run:", err);
    } finally {
      setRunning(false);
    }
  };

  const fallbackLabels: Record<ModeFallbackReason, string> = {
    no_baseline_content: t("fallbackNoBaseline"),
    source_query_changed: t("fallbackQueryChanged"),
    structured_doc_unreadable: t("fallbackDocUnreadable"),
    delta_ops_failed: t("fallbackOpsFailed"),
  };

  const outcomeLabels: Record<RefreshOutcome, string> = {
    content_written: t("outcomeWritten"),
    content_preserved_no_new_facts: t("outcomePreserved"),
    refresh_failed_empty_candidate: t("outcomeFailed"),
  };

  return (
    <div className="space-y-4">
      <div className="rounded-lg border border-border p-3 space-y-3">
        <div>
          <h3 className="text-sm font-semibold text-foreground">{t("title")}</h3>
          <p className="text-xs text-muted-foreground mt-1">{t("description")}</p>
        </div>
        <div className="flex items-center gap-2 flex-wrap">
          <Select value={mode} onValueChange={(v) => setMode(v as ModeChoice)}>
            <SelectTrigger className="w-[220px]">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="stored">{t("modeStored")}</SelectItem>
              <SelectItem value="full">{t("modeFull")}</SelectItem>
              <SelectItem value="delta">{t("modeDelta")}</SelectItem>
            </SelectContent>
          </Select>
          <Button onClick={handleRun} disabled={running}>
            {running ? (
              <Loader2 className="w-4 h-4 mr-2 animate-spin" />
            ) : (
              <FlaskConical className="w-4 h-4 mr-2" />
            )}
            {running ? t("running") : t("runButton")}
          </Button>
        </div>
      </div>

      {result && (
        <div className="space-y-3">
          <SectionCard title={t("summaryTitle")}>
            <Row
              label={t("summaryMode")}
              value={
                result.requested_mode === result.effective_mode
                  ? result.effective_mode
                  : t("summaryModeFellBack", {
                      requested: result.requested_mode,
                      effective: result.effective_mode,
                    })
              }
            />
            {result.mode_fallback_reason && (
              <Row
                label={t("summaryFallbackReason")}
                value={fallbackLabels[result.mode_fallback_reason]}
              />
            )}
            <Row label={t("summaryOutcome")} value={outcomeLabels[result.outcome]} />
            <Row
              label={t("summaryWouldPersist")}
              value={result.would_persist ? t("yes") : t("no")}
            />
            <Row
              label={t("summaryDuration")}
              value={t("traceDuration", { ms: result.duration_ms })}
            />
            <Row
              label={t("summaryTokens")}
              value={t("tokensValue", {
                input: result.usage?.input_tokens ?? 0,
                output: result.usage?.output_tokens ?? 0,
              })}
            />
          </SectionCard>

          <WarningList warnings={result.warnings} title={t("warningsTitle")} />

          <div>
            <h4 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground mb-2">
              {t("diffTitle")}
            </h4>
            <UnifiedDiff diff={result.diff} emptyLabel={t("diffNoChanges")} />
          </div>

          <TraceDetails trace={result.trace} />
        </div>
      )}

      {!result && (
        <div className="space-y-3">
          <h4 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
            {t("lastTraceTitle")}
          </h4>
          {storedTrace ? (
            <>
              <p className="text-xs text-muted-foreground">
                {storedTrace.recorded_at
                  ? t("lastTraceRecordedAt", { time: formatDateTime(storedTrace.recorded_at) })
                  : t("lastTraceDescription")}
              </p>
              <WarningList warnings={storedTrace.warnings ?? []} title={t("warningsTitle")} />
              <TraceDetails trace={storedTrace} />
            </>
          ) : (
            <p className="text-sm text-muted-foreground italic">{t("lastTraceNone")}</p>
          )}
        </div>
      )}
    </div>
  );
}
