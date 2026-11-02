// Ответы API. Суммы — копейки, даты — ISO-строки.

export type Photo = { id: string; url: string };

export type PublicCar = {
  id: string;
  make: string;
  model: string;
  year: number;
  mileage_km: number;
  body_type: string;
  engine: string;
  transmission: string;
  drive: string;
  color: string;
  trim: string;
  condition: string;
  description: string;
  vin_tail: string;
  availability: "in_stock" | "purchasing" | "reserved";
  sale_price_kopecks: number;
  min_down_payment_kopecks: number | null;
  max_term_months: number | null;
  photos: Photo[];
};

export type StaffCar = Omit<PublicCar, "vin_tail"> & {
  vin: string | null;
  ownership_status: "owned" | "purchasing";
  status: string;
  is_published: boolean;
  purchase_price_kopecks?: number | null;
  purchase_date: string | null;
  purchase_document: string;
  created_at: string;
  updated_at: string;
};

export type LedgerRow = {
  seq: number;
  kind: "down_payment" | "installment";
  due_date: string;
  amount_kopecks: number;
  paid_kopecks: number;
  remaining_kopecks: number;
  status: "paid" | "partial" | "overdue" | "due_today" | "upcoming";
};

export type Ledger = {
  total_kopecks: number;
  paid_kopecks: number;
  outstanding_kopecks: number;
  overdue_kopecks: number;
  overdue_items: number;
  oldest_overdue_date: string | null;
  next_due_date: string | null;
  next_due_kopecks: number;
  rows?: LedgerRow[];
};

export type ContractTerms = {
  sale_price_kopecks: number;
  down_payment_kopecks: number;
  financed_kopecks: number;
  term_months: number;
  monthly_payment_kopecks: number;
  contract_date: string;
  first_payment_date: string;
  no_interest_on_delay: boolean;
};

export type CheckItem = { code: string; ok: boolean; message: string; blocking: boolean; info: boolean };

export type Payment = {
  id: string;
  contract_id: string;
  amount_kopecks: number;
  received_on: string;
  method: string;
  document_ref: string;
  note: string;
  status: "confirmed" | "reversed";
  confirmed_at: string;
  reversed_at: string | null;
  reversal_reason: string;
  corrects_payment_id: string | null;
  report_id: string | null;
  contract_number?: string;
  client?: string;
};

export type PaymentReport = {
  id: string;
  contract_id: string;
  amount_kopecks: number;
  paid_on: string;
  comment: string;
  status: "pending" | "matched" | "rejected";
  review_note: string;
  reviewed_at: string | null;
  created_at: string;
  contract_number?: string;
  client?: string;
};

export type StaffContract = ContractTerms & {
  id: string;
  number: string | null;
  status: "draft" | "signed" | "completed" | "cancelled";
  client: { id: string; full_name: string; party_type: string };
  car: { id: string; title: string; vin: string | null };
  application_id: string | null;
  seller_regime: string;
  buyer_type: string;
  is_consumer_deal: boolean;
  disclose_cost_to_buyer: boolean;
  signed_at: string | null;
  completed_at: string | null;
  notes: string;
  created_at: string;
  purchase_price_kopecks?: number;
  markup_kopecks?: number;
  ledger?: Ledger;
  schedule?: { seq: number; kind: string; due_date: string; amount_kopecks: number }[];
  payments?: Payment[];
  reports?: PaymentReport[];
  checks?: { can_sign: boolean; items: CheckItem[] };
};

export type ClientContract = ContractTerms & {
  id: string;
  number: string;
  status: "signed" | "completed";
  signed_at: string | null;
  completed_at: string | null;
  car: { title: string; vin: string | null; color: string; make: string; model: string; year: number };
  ledger: Ledger;
  purchase_price_kopecks?: number;
  markup_kopecks?: number;
  payments?: { id: string; amount_kopecks: number; received_on: string; method: string; status: string }[];
  reports?: PaymentReport[];
};

export type ApplicationEvent = { from_status: string | null; to_status: string; public_message: string; created_at: string };

export type StaffApplication = {
  id: string;
  kind: "catalog" | "custom_order";
  status: string;
  name: string;
  phone: string;
  car: { id: string; title: string; vin: string | null } | null;
  client_id: string | null;
  desired_down_payment_kopecks: number | null;
  desired_term_months: number | null;
  comment: string;
  wanted_make: string;
  wanted_model: string;
  wanted_year: number | null;
  wanted_trim: string;
  max_budget_kopecks: number | null;
  consent_personal_data: boolean;
  consent_version: string;
  public_message: string;
  internal_note: string;
  public_token: string;
  created_at: string;
  updated_at: string;
  events: ApplicationEvent[];
};

export type PublicApplication = {
  kind: string;
  status: string;
  created_at: string;
  updated_at: string;
  car_title: string | null;
  wanted: string | null;
  public_message: string;
  history: { status: string; message: string; at: string }[];
};

export type ThreadMessage = { id: string; from_staff: boolean; body: string; created_at: string; author: string };

export type Thread = {
  id: string;
  topic: string;
  subject: string;
  status: string;
  contract_id: string | null;
  created_at: string;
  updated_at: string;
  client?: { id: string; full_name: string };
  messages?: ThreadMessage[];
  contract?: StaffContract;
};

export type AppNotification = {
  id: string;
  kind: string;
  title: string;
  body: string;
  link: string;
  created_at: string;
  read: boolean;
};

// ---------- Версия 2 ----------

export type DocCheck = { code: string; level: "ok" | "info" | "warning" | "error"; message: string };

export type DocBlock =
  | { type: "h1" | "h2" | "p" | "note"; text: string }
  | { type: "table"; header: string[] | null; rows: string[][]; footer: string[] | null }
  | { type: "signatures"; parties: { title: string; name: string }[] };

export type TemplateParam = { name: string; label: string; required?: boolean; type?: "bool" };

export type DocTemplate = {
  code: string;
  title: string;
  version: string;
  scope: "contract" | "client" | "car";
  description: string;
  requires: string[];
  params: TemplateParam[];
  requires_signed_contract: boolean;
  visible_to_client: boolean;
  lawyer_points: string[];
  approved: boolean;
  approval: { lawyer_name: string; approved_at: string; note: string } | null;
};

export type DocItem = {
  id: string;
  title: string;
  template_code: string;
  template_version: string;
  template_approved: boolean;
  status: "draft" | "pending_approval" | "approved" | "signed" | "cancelled";
  contract_id: string | null;
  client_id: string | null;
  addendum_id: string | null;
  visible_to_client: boolean;
  created_at: string;
  approved_at: string | null;
  signed_on: string | null;
  has_signed_file: boolean;
  final: boolean;
  watermark: string;
  body_sha256: string;
  cancelled_reason: string;
  checks: DocCheck[];
  blocks?: DocBlock[];
  params?: Record<string, string | boolean>;
};

export type OutMessage = {
  id: string;
  client: string | null;
  client_id: string;
  contract_id: string | null;
  contract_number: string | null;
  channel: "internal" | "sms" | "email";
  purpose: string;
  body: string;
  address_masked: string;
  status: "scheduled" | "sent" | "failed" | "cancelled" | "skipped";
  status_reason: string;
  scheduled_for: string;
  sent_at: string | null;
  attempts: number;
  provider: string;
  created_at: string;
};

export type Pledge = {
  id: string;
  contract_id: string;
  contract_number: string;
  contract_status: string;
  client: string;
  car: string;
  vin: string | null;
  status: string;
  registry_number: string;
  registered_on: string | null;
  notary: string;
  release_number: string;
  released_on: string | null;
  notes: string;
  updated_at: string;
  allowed_next: string[];
};

export type InsurancePolicy = {
  id: string;
  car_id: string;
  car: string;
  vin: string | null;
  contract_id: string | null;
  kind: string;
  number: string;
  insurer: string;
  valid_from: string;
  valid_to: string;
  required_by_contract: boolean;
  notes: string;
};

export type StaffTask = {
  id: string;
  kind: string;
  title: string;
  description: string;
  due_date: string | null;
  status: "open" | "done" | "cancelled";
  link: string;
  created_at: string;
  done_at: string | null;
  result_note: string;
  automatic: boolean;
};
