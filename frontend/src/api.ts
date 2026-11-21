import type { Capacity, Overview, PackInfo, PersonDetail, PersonRow, Run, WhatIfBody } from "./types";

async function call<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, init);
  if (!res.ok) {
    let msg = `${res.status} ${res.statusText}`;
    try { const b = await res.json(); if (b.detail) msg = typeof b.detail === "string" ? b.detail : JSON.stringify(b.detail); } catch { /* keep default */ }
    throw new Error(msg);
  }
  return res.json() as Promise<T>;
}
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
  setStatus: (id: number, status: string) => call<{ run_status: Run["run_status"] }>(`/api/schedule/${id}/status`, post({ status })),
};
