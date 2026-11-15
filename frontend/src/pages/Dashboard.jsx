import { useState } from 'react';
import { Link } from 'react-router-dom';
import { dashboardApi } from '../api/index.js';
import Badge, { DomainStatusBadge } from '../components/Badge.jsx';
import EventItem from '../components/EventItem.jsx';
import { IconAlert, IconRefresh, IconSearch } from '../components/Icons.jsx';
import PageHeader, { EmptyState, ErrorBox } from '../components/PageHeader.jsx';
import Spinner from '../components/Spinner.jsx';
import { useToast } from '../components/Toast.jsx';
import usePolling from '../hooks/usePolling.js';
import { formatDuration, formatRelative, isIPv4 } from '../utils/format.js';
import '../styles/dashboard.css';

const INTEGRATION_NAMES = { remnawave: 'Remnawave', cloudflare: 'Cloudflare', telegram: 'Telegram' };

function StatCard({ label, value, total, tone, hint, to }) {
  const body = (
    <>
      <span className="stat__label">{label}</span>
      <span className={`stat__value stat__value--${tone}`}>
        {value}
        {total !== undefined && <span className="stat__total">/{total}</span>}
      </span>
      {hint && <span className="stat__hint">{hint}</span>}
    </>
  );
  return to ? (
    <Link to={to} className="stat card card--link">
      {body}
    </Link>
  ) : (
    <div className="stat card">{body}</div>
  );
}

function IpTool() {
  const [ip, setIp] = useState('');
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState(null);
  const [error, setError] = useState('');

  const run = async (e) => {
    e.preventDefault();
    if (!isIPv4(ip)) {
      setError('Введите корректный IPv4');
      return;
    }
    setBusy(true);
    setError('');
    setResult(null);
    try {
      setResult(await dashboardApi.checkIp(ip.trim()));
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className="card panel">
      <h2 className="panel__title">Проверить IP</h2>
      <form className="ip-tool" onSubmit={run}>
        <input
          className="input mono"
          placeholder="1.2.3.4"
          value={ip}
          onChange={(e) => setIp(e.target.value)}
          inputMode="decimal"
        />
        <button type="submit" className="btn btn--primary" disabled={busy}>
          {busy ? <Spinner size={16} /> : <IconSearch size={18} />}
          <span>Проверить</span>
        </button>
      </form>
      {error && <div className="alert alert--bad">{error}</div>}
      {result && (
        <div className="ip-tool__result">
          <span className="mono">{result.ip}</span>
          {result.blocked === true && <Badge tone="bad">В бане</Badge>}
          {result.blocked === false && <Badge tone="ok">Доступен</Badge>}
          {result.blocked === null && <Badge tone="warn">Не удалось проверить</Badge>}
          {Object.entries(result.details).map(([name, d]) => (
            <div key={name} className="ip-tool__source">
              <b>{name}</b>: {d.error ? d.error : d.blocked ? 'заблокирован' : 'чисто'}
              {d.geo ? ` · ${d.geo}` : ''}
              {d.blocked_subnets?.length ? ` · подсети: ${d.blocked_subnets.join(', ')}` : ''}
            </div>
          ))}
        </div>
      )}
    </section>
  );
}

export default function Dashboard() {
  const toast = useToast();
  const { data, error, loading, reload } = usePolling(dashboardApi.get, 15000);
  const [starting, setStarting] = useState(false);

  const checkNow = async () => {
    setStarting(true);
    try {
      await dashboardApi.checkNow();
      toast.info('Проверка запущена');
      setTimeout(reload, 1500);
    } catch (e) {
      toast.error(e.message);
    } finally {
      setStarting(false);
    }
  };

  if (loading && !data) {
    return (
      <div className="page-loading">
        <Spinner size={28} />
      </div>
    );
  }

  const st = data?.status;
  const running = st?.check?.running;
  const missing = st ? Object.entries(st.integrations).filter(([, ok]) => !ok) : [];

  return (
    <div className="page">
      <PageHeader
        title="Дашборд"
        subtitle={
          st &&
          (running
            ? 'Идёт проверка доменов…'
            : `Последняя проверка: ${formatRelative(st.check.last_finished_at)} · следующая: ${formatRelative(st.check.next_at)}`)
        }
        actions={
          <button type="button" className="btn btn--primary" onClick={checkNow} disabled={starting || running}>
            {running || starting ? <Spinner size={16} /> : <IconRefresh size={18} />}
            <span>Проверить сейчас</span>
          </button>
        }
      />

      <ErrorBox error={error} onRetry={reload} />

      {missing.length > 0 && (
        <div className="alert alert--warn">
          <IconAlert size={18} />
          <span>
            Не настроено в .env: {missing.map(([k]) => INTEGRATION_NAMES[k]).join(', ')}
          </span>
        </div>
      )}
      {st?.active_errors?.map((e) => (
        <div key={e.key} className="alert alert--bad">
          <IconAlert size={18} />
          <span>{e.message}</span>
        </div>
      ))}

      {data && (
        <>
          <div className="stats">
            <StatCard
              label="Ноды online"
              value={data.nodes.online}
              total={data.nodes.total}
              tone={data.nodes.online === data.nodes.total ? 'ok' : 'bad'}
              hint={data.nodes.disabled ? `отключено: ${data.nodes.disabled}` : 'все активные ноды'}
              to="/nodes"
            />
            <StatCard
              label="Домены в порядке"
              value={data.domains.by_status.ok || 0}
              total={data.domains.total}
              tone={data.domains.problems.length ? 'warn' : 'ok'}
              hint={data.domains.problems.length ? `проблем: ${data.domains.problems.length}` : 'проблем нет'}
              to="/domains"
            />
            <StatCard
              label="IP в бане"
              value={data.ips.blocked}
              total={data.ips.total}
              tone={data.ips.blocked ? 'bad' : 'ok'}
              hint={`доступно: ${data.ips.clean}${data.ips.unknown ? ` · не проверено: ${data.ips.unknown}` : ''}`}
            />
            <StatCard
              label="Смен IP за 24 ч"
              value={data.last_24h.switches_auto + data.last_24h.switches_manual}
              tone="accent"
              hint={`авто: ${data.last_24h.switches_auto} · вручную: ${data.last_24h.switches_manual} · банов: ${data.last_24h.blocked}`}
              to="/events"
            />
          </div>

          <div className="dash-grid">
            <section className="card panel">
              <h2 className="panel__title">Требует внимания</h2>
              {data.nodes.offline.length === 0 && data.domains.problems.length === 0 ? (
                <EmptyState title="Всё работает" text="Нет упавших нод и проблемных доменов" />
              ) : (
                <ul className="attention">
                  {data.nodes.offline.map((n) => (
                    <li key={n.uuid} className="attention__item">
                      <Badge tone="bad">Offline</Badge>
                      <div className="attention__body">
                        <Link to="/nodes" className="attention__name">
                          {n.name}
                        </Link>
                        <span className="attention__meta">
                          {n.address}
                          {n.since ? ` · ${formatDuration(n.since)}` : ''}
                          {n.message ? ` · ${n.message}` : ''}
                        </span>
                      </div>
                    </li>
                  ))}
                  {data.domains.problems.map((d) => (
                    <li key={d.id} className="attention__item">
                      <DomainStatusBadge status={d.status} />
                      <div className="attention__body">
                        <Link to={`/domains/${d.id}`} className="attention__name">
                          {d.name}
                        </Link>
                        <span className="attention__meta">
                          <span className="mono">{d.current_ip || 'нет IP'}</span>
                          {d.message ? ` · ${d.message}` : ''}
                        </span>
                      </div>
                    </li>
                  ))}
                </ul>
              )}
            </section>

            <section className="card panel">
              <div className="panel__head">
                <h2 className="panel__title">Последние события</h2>
                <Link to="/events" className="link-sm">
                  Все события →
                </Link>
              </div>
              {data.recent_events.length === 0 ? (
                <EmptyState title="Событий пока нет" />
              ) : (
                <ul className="event-list">
                  {data.recent_events.map((e) => (
                    <EventItem key={e.id} event={e} compact />
                  ))}
                </ul>
              )}
            </section>
          </div>

          <IpTool />
        </>
      )}
    </div>
  );
}
