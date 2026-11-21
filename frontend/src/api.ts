import type { AIChange, AIStatus, Capacity, Facets, Overview, PackInfo, PersonDetail, PersonRow, Preview, Proposal, Rule, RuleDraft, Run, WhatIfBody } from "./types";

async function call<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, init);
  if (!res.ok) {
    let msg = `${res.status} ${res.statusText}`;
    try { const b = await res.json(); if (b.detail) msg = typeof b.detail === "string" ? b.detail : Array.isArray(b.detail) ? b.detail.map((d: unknown) => typeof d === "string" ? d : JSON.stringify(d)).join(" ") : JSON.stringify(b.detail); } catch { /* keep default */ }
    throw new Error(msg);
  }
  return res.json() as Promise<T>;
}
const send = (method: string, body?: unknown): RequestInit => ({
  method, headers: { "Content-Type": "application/json" }, body: body === undefined ? undefined : JSON.stringify(body),
});
const post = (body?: unknown): RequestInit => ({
  method: "POST", headers: { "Content-Type": "application/json" }, body: body === undefined ? undefined : JSON.stringify(body),
});

export const api = {
  packs: () => call<PackInfo[]>("/api/packs"),
  overview: (p: string) => call<Overview>(`/api/${p}/overview`),
  people: (p: string, q: URLSearchParams) => call<PersonRow[]>(`/api/${p}/people?${q}`),
  person: (p: string, id: number) => call<PersonDetail>(`/api/${p}/people/${id}`),
  capacity: (p: string) => call<Capacity>(`/api/${p}/capacity`),
  latest: (p: string) => call<Run | null>(`/api/${p}/schedule/latest`),
  run: (id: number) => call<Run>(`/api/schedule/${id}`),
  optimize: (p: string) => call<Run>(`/api/${p}/schedule`, post()),
  whatIf: (p: string, runId: number, w: WhatIfBody) => call<Run>(`/api/${p}/schedule/${runId}/what-if`, post(w)),
  rules: (p: string) => call<{ rules: Rule[]; facets: Facets; rules_version: number }>(`/api/${p}/rules`),
  previewRule: (p: string, r: RuleDraft, id?: string) => call<Preview>(`/api/${p}/rules/preview${id ? `?rule_id=${id}` : ""}`, post(r)),
  createRule: (p: string, r: RuleDraft) => call<Rule>(`/api/${p}/rules`, post(r)),
  updateRule: (p: string, id: string, r: RuleDraft) => call<Rule>(`/api/${p}/rules/${id}`, send("PUT", r)),
  deleteRule: (p: string, id: string) => call<{ deleted: string }>(`/api/${p}/rules/${id}`, send("DELETE")),
  reset: (p: string) => call<{ reset: string }>(`/api/${p}/reset`, post()),
  aiStatus: () => call<AIStatus>("/api/ai/status"),
  aiRules: (p: string, text: string) => call<{ mode: string; proposals: Proposal[]; unclear: string[] }>(`/api/${p}/ai/rules`, post({ text })),
  aiWhatIf: (p: string, text: string, runId: number) => call<AIChange>(`/api/${p}/ai/what-if`, post({ text, run_id: runId })),
  aiAsk: (p: string, question: string, runId: number) => call<{ mode: string; answer: string; grounded_on: string[] }>(`/api/${p}/ai/ask`, post({ question, run_id: runId })),
  setStatus: (id: number, status: string) => call<{ run_status: Run["run_status"] }>(`/api/schedule/${id}/status`, post({ status })),
};
