import { Link } from 'react-router-dom';
import { investigationsApi } from '../api/index.js';
import { formatDateTime, formatRelative, INVESTIGATION_STATUS } from '../utils/format.js';
import Badge from './Badge.jsx';
import { useToast } from './Toast.jsx';

function Progress({ inv }) {
  const results = (inv.results || []).filter((r) => r.blocked !== null && r.blocked !== undefined);
  const dots = Array.from({ length: inv.checks_total }, (_, i) => results[i]);
  return (
    <span className="inv-progress" title={`Проверок: ${inv.checks_done} из ${inv.checks_total}`}>
      {dots.map((r, i) => (
        <span
          // eslint-disable-next-line react/no-array-index-key
          key={i}
          className={`inv-dot ${r ? (r.blocked ? 'inv-dot--bad' : 'inv-dot--ok') : ''}`}
        />
      ))}
    </span>
  );
}

export default function InvestigationList({ items, showDomain = true, onChanged }) {
  const toast = useToast();

  const cancel = async (inv) => {
    try {
      await investigationsApi.cancel(inv.id);
      toast.success('Проверка отменена');
      onChanged?.();
    } catch (e) {
      toast.error(e.message);
    }
  };

  return (
    <ul className="inv-list">
      {items.map((inv) => {
        const st = INVESTIGATION_STATUS[inv.status] || INVESTIGATION_STATUS.failed;
        const active = inv.status === 'active';
        return (
          <li key={inv.id} className="inv">
            <div className="inv__head">
              <Badge tone={st.tone}>{st.label}</Badge>
              {showDomain && (
                <Link to={`/domains/${inv.domain_id}`} className="inv__domain">
                  {inv.domain_name}
                </Link>
              )}
              {inv.ip && <span className="mono muted small">{inv.ip}</span>}
              <Progress inv={inv} />
            </div>
            <p className="inv__reason">
              {inv.node_name ? `${inv.node_name}: ` : ''}
              {inv.reason}
            </p>
            {inv.summary && <p className="inv__summary">{inv.summary}</p>}
            <div className="inv__foot">
              <span className="muted small">
                начата {formatDateTime(inv.started_at)}
                {active && inv.next_check_at && ` · следующая проверка ${formatRelative(inv.next_check_at)}`}
              </span>
              {active && (
                <button type="button" className="btn btn--sm btn--ghost" onClick={() => cancel(inv)}>
                  Отменить
                </button>
              )}
            </div>
          </li>
        );
      })}
    </ul>
  );
}
