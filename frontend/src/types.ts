export interface PartLabel {
  pk: number;
  name: string;
  ipn: string;
  description: string;
  category_name?: string;
  active?: boolean;
  component?: boolean;
  stock?: number;
  units?: string;
  mpns?: { manufacturer: string; mpn: string }[];
  known?: number;
  derived?: number;
  missing?: boolean;
}

/**
 * How two parts can replace each other, read from the first one:
 * both = interchangeable, forward = the other part can replace this one,
 * reverse = this part can replace the other, none = neither.
 */
export type Direction = 'both' | 'forward' | 'reverse' | 'none';

export type Verdict = 'match' | 'better' | 'close' | 'worse' | 'differ' | 'missing';

export interface CompareRow {
  key: string;
  label: string;
  level: 'critical' | 'major' | 'minor';
  a: string | null;
  b: string | null;
  derived: boolean;
  verdict: Verdict;
}

export interface MatchInfo {
  strength: number;
  direction: Direction;
  basis: 'parameters' | 'name' | 'mpn' | 'bom';
  coverage?: number;
  same_mpn?: boolean;
  rows?: CompareRow[];
}

export interface Candidate extends MatchInfo {
  /** Only set in the overview, where a candidate is a pair */
  part?: number;
  other: number;
  substitute_on: number;
  used_in?: number;
}

export interface LinkEntry {
  /** Only set in the overview */
  part?: number;
  other: number;
  relation: Direction;
  two_way: boolean;
  note: string;
  by: string;
  at: string;
  stored_on: number;
  match: MatchInfo | null;
  problems: string[];
}

export interface UsageLine {
  line: number;
  assembly: number;
  reference: string;
  locked: boolean;
  substitutes: { part: number; managed: boolean }[];
  add: number[];
  remove: number[];
  skipped: boolean;
}

export interface Permissions {
  view: boolean;
  link: boolean;
  sync: boolean;
  enrich: boolean;
}

export interface Settings {
  min_strength: number;
  use_description: boolean;
  include_assemblies: boolean;
  include_inactive: boolean;
  auto_sync: boolean;
  skip_locked: boolean;
  create_templates: boolean;
  digikey: boolean;
  lcsc: boolean;
}

export interface Attribute {
  key: string;
  label: string;
  text: string;
  derived: boolean;
}

export interface PartResult {
  version: string;
  generated: string;
  part: PartLabel & { eligible: boolean; skus: { supplier: string; sku: string }[] };
  attributes: Attribute[];
  links: LinkEntry[];
  candidates: Candidate[];
  dismissed: Candidate[];
  usage: UsageLine[];
  pending: number;
  bom_lines: number;
  parts: Record<string, PartLabel>;
  settings: Settings;
  permissions: Permissions;
}

export interface SyncChange {
  line: number;
  assembly: number;
  sub_part: number;
  reference: string;
  add: number[];
  remove: number[];
  skipped: boolean;
}

export interface OverviewResult {
  version: string;
  generated: string;
  summary: {
    parts: number;
    eligible: number;
    links: number;
    candidates: number;
    duplicates: number;
    pending: number;
    thin: number;
    bom_lines: number;
  };
  links: LinkEntry[];
  candidates: Candidate[];
  by_hand: { part: number; other: number; lines: number; missing: number; dismissed: boolean }[];
  duplicates: { mpn: string; parts: number[] }[];
  sync: { add: number; remove: number; skipped: number; lines: SyncChange[]; more: number };
  thin: { part: number; used_in: number }[];
  usage: Record<string, number>;
  parts: Record<string, PartLabel>;
  settings: Settings;
  permissions: Permissions;
}

export interface SyncResult {
  added: number;
  removed: number;
  skipped: number;
  errors: { line: number; part: number; error: string }[];
}

export interface Proposal {
  source: string;
  name: string;
  found: string;
  role: string | null;
  template: number | null;
  template_name: string;
  units: string;
  value: string | null;
  current: string | null;
  action: 'add' | 'create' | 'keep' | 'skip';
  reason: string;
}

export interface EnrichResult {
  part: number;
  proposals: Proposal[];
  report: { source: string; status: 'found' | 'none' | 'off' | 'error'; detail: string; url?: string }[];
  applied?: { added: { name: string; value: string }[]; errors: { name: string; error: string }[] };
}

export type Lookup = (pk: number | null | undefined) => PartLabel | undefined;
