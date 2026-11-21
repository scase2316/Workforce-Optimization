export interface Vocab {
  name: string; tagline: string; person: string; people: string; group: string; groups: string; disclaimer: string;
  commitment_types: Record<string, string>;
}
export interface PackInfo { id: string; name: string; tagline: string; vocabulary: Vocab }
export interface GroupRow {
  group_id: number; name: string; people: number; min_available: number;
  complete: number; expiring: number; gap: number; overdue: number; readiness_pct: number;
}
export interface Overview {
  as_of: string; vocabulary: Vocab;
  totals: { people: number; items: number; complete: number; expiring: number; gap: number; overdue: number; readiness_pct: number };
  groups: GroupRow[];
  requirements: { id: string; name: string; complete: number; expiring: number; gap: number; overdue: number }[];
}
export interface PersonRow {
  person_id: number; name: string; role: string; group_id: number; readiness_pct: number;
  overdue: number; gap: number; expiring: number;
}
export interface PersonItem { requirement_id: string; name: string; status: string; due: string | null; blocked_by: string[] }
export interface PersonDetail {
  person_id: number; name: string; role: string; group: string; start_date: string; readiness_pct: number; items: PersonItem[];
}
export interface CapacityGroup { group_id: number; name: string; size: number; min_available: number; base: number[]; planned: number[] }
export interface CommitmentRow { id: number; group_id: number; type: string; name: string; start: number; end: number; people: number | null }
export interface Capacity { as_of: string; horizon_days: number; groups: CapacityGroup[]; commitments: CommitmentRow[] }
export interface Rationale {
  status: string; due: string | null; days_until_start: number; meets_deadline: boolean; days_after_deadline: number;
  earlier_options: { offering_id: number; start: string; reason: string }[];
}
export interface Assignment {
  person_id: number; person: string; group_id: number; requirement_id: string; requirement: string;
  offering_id: number; start: string; end: string; location: string; rationale: Rationale;
}
export interface Unscheduled { person_id: number; person: string; requirement_id: string; requirement: string; status: string; reason: string }
export interface Summary {
  items_outstanding: number; scheduled: number; unscheduled: number; overdue_cleared: number; on_time: number;
  readiness_before_pct: number; readiness_after_pct: number;
  by_group: { group_id: number; group: string; before_pct: number; after_pct: number }[];
}
export interface Diff {
  added: Assignment[]; removed: Assignment[]; unchanged: number;
  moved: { person: string; requirement: string; from: string; to: string }[];
}
export interface Run {
  run_id: number; run_status: "proposed" | "approved" | "rejected"; parent_run_id: number | null;
  status: string; optimal: boolean; runtime_s: number;
  assignments: Assignment[]; unscheduled: Unscheduled[]; summary: Summary; capacity: Capacity;
  diff: Diff | null; compared_to?: { run_id: number; summary: Summary };
  manning: { group_id: number; group: string; min_available: number; lowest_available: number; on: string | null }[];
}
export interface WhatIfBody {
  shift?: { commitment_id: number; days: number }[];
  seat_cap?: { requirement_id: string; seats: number }[];
}
