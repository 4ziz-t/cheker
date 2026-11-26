import { useMemo, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { domainsApi } from '../api/index.js';
import AddDomainModal from '../components/AddDomainModal.jsx';
import { DomainStatusBadge } from '../components/Badge.jsx';
import { IconChevronRight, IconPlus, IconSearch } from '../components/Icons.jsx';
import PageHeader, { EmptyState, ErrorBox } from '../components/PageHeader.jsx';
import OnlyBanner, { useOnlyFilter } from '../components/OnlyBanner.jsx';
import Spinner from '../components/Spinner.jsx';
import { useToast } from '../components/Toast.jsx';
import Toggle from '../components/Toggle.jsx';
import UnlinkedCheckPanel from '../components/UnlinkedCheckPanel.jsx';
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
  const { only, title: onlyTitle, clear: clearOnly } = useOnlyFilter();

  const list = useMemo(() => {
    const q = query.trim().toLowerCase();
    return (data || []).filter((d) => {
      if (only && !only.has(String(d.id))) return false;
      if (q && !d.name.includes(q) && !(d.current_ip || '').includes(q)) return false;
      if (filter === 'disabled') return !d.enabled;
      if (filter === 'ok') return d.enabled && d.status === 'ok';
      if (filter === 'problems') return d.enabled && d.status !== 'ok';
      return true;
    });
  }, [data, query, filter, only]);

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

      {data && <UnlinkedCheckPanel unlinkedCount={data.filter((d) => d.enabled && !d.nodes.length).length} />}

      {only && <OnlyBanner title={onlyTitle} count={list.length} onClear={clearOnly} />}

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
        <div className="domain-list">
          <div className="domain-row domain-row--head" aria-hidden="true">
            <span>Домен / IP</span>
            <span>Статус</span>
            <span>Текущий IP</span>
            <span>Список IP</span>
            <span>Проверено</span>
            <span>Автосмена</span>
            <span />
          </div>
          {list.map((d) => {
            const blocked = d.ips.filter((i) => i.is_blocked === true).length;
            const open = () => navigate(`/domains/${d.id}`);
            return (
              <div
                key={d.id}
                role="link"
                tabIndex={0}
                title={`Открыть ${d.name}`}
                className={`card domain-row row-card--clickable domain-row--${d.enabled ? d.status : 'off'} ${
                  !d.enabled ? 'is-off' : ''
                }`}
                onClick={open}
                onKeyDown={(e) => {
                  if (e.key === 'Enter' && e.target === e.currentTarget) open();
                }}
              >
                <div className="domain-row__main">
                  <Link to={`/domains/${d.id}`} className="domain-row__name" onClick={(e) => e.stopPropagation()}>
                    {d.name}
                  </Link>
                  <div className="domain-row__tags">
                    {d.kind === 'ip' && <span className="tag">IP-адрес</span>}
                    {d.source === 'remnawave' && <span className="tag tag--muted">из Remnawave</span>}
                    {d.nodes.length ? (
                      <span className="tag tag--muted" title="Проверяется при падении скорости ноды">
                        нода: {d.nodes.join(', ')}
                      </span>
                    ) : (
                      <span className="tag tag--warn" title="Проверяется только автопроверкой без ноды или вручную">
                        без ноды
                      </span>
                    )}
                  </div>
                  {d.status_message && d.status !== 'ok' && (
                    <p className={`domain-row__msg text-${DOMAIN_STATUS[d.status]?.tone || 'muted'}`}>
                      {d.status_message}
                    </p>
                  )}
                </div>

                <div className="domain-row__cell domain-row__status" data-label="Статус">
                  {d.enabled ? <DomainStatusBadge status={d.status} /> : <span className="muted">Выключен</span>}
                </div>

                <div className="domain-row__cells">
                  <div className="domain-row__cell domain-row__cell--ip" data-label="Текущий IP">
                    <span className="mono domain-row__ip">{d.current_ip || '—'}</span>
                  </div>
                  <div className="domain-row__cell domain-row__pool" data-label="Список IP">
                    <IpDots ips={d.ips} current={d.current_ip} />
                    <span className="muted small">
                      {d.ips.length} IP{blocked ? ` · в бане ${blocked}` : ''}
                    </span>
                  </div>
                  <div className="domain-row__cell domain-row__cell--checked" data-label="Проверено">
                    <span className="muted">{formatRelative(d.last_checked_at)}</span>
                  </div>
                  <div
                    className="domain-row__cell domain-row__auto"
                    data-label="Автосмена"
                    onClick={(e) => e.stopPropagation()}
                    onKeyDown={(e) => e.stopPropagation()}
                    role="presentation"
                  >
                    {d.kind === 'ip' ? (
                      <span className="muted small">Только мониторинг</span>
                    ) : (
                      <Toggle checked={d.auto_switch} onChange={(v) => toggleAuto(d, v)} label="" />
                    )}
                  </div>
                </div>

                <span className="row-card__chevron" aria-hidden="true">
                  <IconChevronRight size={20} />
                </span>
              </div>
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
