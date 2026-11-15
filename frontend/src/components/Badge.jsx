import { DOMAIN_STATUS } from '../utils/format.js';

export default function Badge({ tone = 'muted', children, dot = true }) {
  return (
    <span className={`badge badge--${tone}`}>
      {dot && <span className="badge__dot" />}
      {children}
    </span>
  );
}

export function DomainStatusBadge({ status }) {
  const s = DOMAIN_STATUS[status] || DOMAIN_STATUS.unknown;
  return <Badge tone={s.tone}>{s.label}</Badge>;
}
