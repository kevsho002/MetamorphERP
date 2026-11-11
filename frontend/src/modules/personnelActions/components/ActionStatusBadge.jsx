const CLASS = {
  DRAFT: "badge--muted",
  PENDING: "badge--warn",
  APPROVED: "badge--ok",
  REJECTED: "badge--error",
  CANCELLED: "badge--muted",
};

export default function ActionStatusBadge({ status, label }) {
  return <span className={`badge ${CLASS[status] ?? "badge--muted"}`}>{label ?? status}</span>;
}
