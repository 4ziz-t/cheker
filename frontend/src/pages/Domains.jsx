import { useMemo, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { domainsApi } from '../api/index.js';
import AddDomainModal from '../components/AddDomainModal.jsx';
import { DomainStatusBadge } from '../components/Badge.jsx';
import { IconPlus, IconSearch } from '../components/Icons.jsx';
import PageHeader, { EmptyState, ErrorBox } from '../components/PageHeader.jsx';
import Spinner from '../components/Spinner.jsx';
import { useToast } from '../components/Toast.jsx';
import Toggle from '../components/Toggle.jsx';
import usePolling from '../hooks/usePolling.js';
import { DOMAIN_STATUS, formatRelative, ipState } from '../utils/format.js';
import '../styles/domains.css';

const FILTERS = [
  { key: 'all', label: 'Все' },
  { key: 'problems', label: 'Проблемные' },
  { key: 'ok', label: 'В порядке' },
  { key: 'disabled', label: 'Выключенные' },
];

function IpDots({ ips, current }) {
  return (
    <div className="ip-dots">
      {ips.map((ip) => (
        <span
          key={ip.id}
          className={`ip-dot ip-dot--${ipState(ip).tone} ${ip.ip === current ? 'is-current' : ''}`}
          title={`${ip.ip} — ${ipState(ip).label}${ip.ip === current ? ' (текущий)' : ''}`}
        />
      ))}
    </div>
  );
}

export default function Domains() {
  const toast = useToast();
  const navigate = useNavigate();
  const { data, setData, error, loading, reload } = usePolling(domainsApi.list, 20000);
  const [adding, setAdding] = useState(false);
  const [query, setQuery] = useState('');
  const [filter, setFilter] = useState('all');

  const list = useMemo(() => {
    const q = query.trim().toLowerCase();
    return (data || []).filter((d) => {
      if (q && !d.name.includes(q) && !(d.current_ip || '').includes(q)) return false;
      if (filter === 'disabled') return !d.enabled;
      if (filter === 'ok') return d.enabled && d.status === 'ok';
      if (filter === 'problems') return d.enabled && d.status !== 'ok';
      return true;
    });
  }, [data, query, filter]);

  const toggleAuto = async (domain, value) => {
    try {
      const updated = await domainsApi.update(domain.id, { auto_switch: value });
      setData((prev) => prev.map((d) => (d.id === updated.id ? updated : d)));
      toast.success(value ? 'Автосмена включена' : 'Автосмена выключена');
    } catch (e) {
      toast.error(e.message);
    }
  };

  return (
    <div className="page">
      <PageHeader
        title="Домены"
        subtitle={data ? `Всего: ${data.length}` : ''}
        actions={
          <button type="button" className="btn btn--primary" onClick={() => setAdding(true)}>
            <IconPlus size={18} />
            <span>Добавить</span>
          </button>
        }
      />

      <div className="toolbar">
        <div className="search">
          <IconSearch size={18} />
          <input
            className="input"
            placeholder="Поиск по домену или IP"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
        </div>
        <div className="chips">
          {FILTERS.map((f) => (
            <button
              key={f.key}
              type="button"
              className={`chip ${filter === f.key ? 'is-active' : ''}`}
              onClick={() => setFilter(f.key)}
            >
              {f.label}
            </button>
          ))}
        </div>
      </div>

      <ErrorBox error={error} onRetry={reload} />

      {loading && !data ? (
        <div className="page-loading">
          <Spinner size={28} />
        </div>
      ) : list.length === 0 ? (
        <EmptyState
          title={data?.length ? 'Ничего не найдено' : 'Доменов пока нет'}
          text={data?.length ? 'Измените фильтр или запрос' : 'Добавьте домен и список IP для него'}
          action={
            !data?.length && (
              <button type="button" className="btn btn--primary" onClick={() => setAdding(true)}>
                <IconPlus size={18} />
                <span>Добавить домен</span>
              </button>
            )
          }
        />
      ) : (
        <div className="domain-grid">
          {list.map((d) => {
            const blocked = d.ips.filter((i) => i.is_blocked === true).length;
            return (
              <article key={d.id} className={`card domain-card ${!d.enabled ? 'is-off' : ''}`}>
                <div className="domain-card__head">
                  <Link to={`/domains/${d.id}`} className="domain-card__name">
                    {d.name}
                  </Link>
                  {d.enabled ? <DomainStatusBadge status={d.status} /> : <span className="muted">Выключен</span>}
                </div>

                {(d.kind === 'ip' || d.source === 'remnawave') && (
                  <div className="domain-card__tags">
                    {d.kind === 'ip' && <span className="tag">IP-адрес</span>}
                    {d.source === 'remnawave' && <span className="tag tag--muted">из Remnawave</span>}
                  </div>
                )}

                <div className="domain-card__ip">
                  <span className="muted">Текущий IP</span>
                  <span className="mono domain-card__current">{d.current_ip || '—'}</span>
                </div>

                <div className="domain-card__pool">
                  <IpDots ips={d.ips} current={d.current_ip} />
                  <span className="muted">
                    {d.ips.length} IP{blocked ? ` · в бане ${blocked}` : ''}
                  </span>
                </div>

                {d.status_message && d.status !== 'ok' && (
                  <p className={`domain-card__msg text-${DOMAIN_STATUS[d.status]?.tone || 'muted'}`}>
                    {d.status_message}
                  </p>
                )}

                <div className="domain-card__foot">
                  {d.kind === 'ip' ? (
                    <span className="muted small">Только мониторинг</span>
                  ) : (
                    <Toggle checked={d.auto_switch} onChange={(v) => toggleAuto(d, v)} label="Автосмена" />
                  )}
                  <span className="muted small">{formatRelative(d.last_checked_at)}</span>
                </div>
              </article>
            );
          })}
        </div>
      )}

      {adding && (
        <AddDomainModal
          onClose={() => setAdding(false)}
          onCreated={(domain) => {
            setAdding(false);
            toast.success(`Домен ${domain.name} добавлен, идёт проверка`);
            navigate(`/domains/${domain.id}`);
          }}
        />
      )}
    </div>
  );
}
