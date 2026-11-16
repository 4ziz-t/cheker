import { useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import { nodesApi } from '../api/index.js';
import Badge, { DomainStatusBadge } from '../components/Badge.jsx';
import { IconPower, IconRefresh, IconSearch } from '../components/Icons.jsx';
import { ConfirmModal } from '../components/Modal.jsx';
import PageHeader, { EmptyState, ErrorBox } from '../components/PageHeader.jsx';
import Spinner from '../components/Spinner.jsx';
import { useToast } from '../components/Toast.jsx';
import usePolling from '../hooks/usePolling.js';
import { formatDuration, formatRelative, formatSpeed } from '../utils/format.js';
import '../styles/nodes.css';

function nodeState(n) {
  if (n.is_disabled) return { key: 'disabled', label: 'Отключена', tone: 'muted' };
  if (n.is_connected) return { key: 'online', label: 'Online', tone: 'ok' };
  if (n.is_connecting) return { key: 'offline', label: 'Подключается', tone: 'warn' };
  return { key: 'offline', label: 'Offline', tone: 'bad' };
}

const FILTERS = [
  { key: 'all', label: 'Все' },
  { key: 'offline', label: 'Offline' },
  { key: 'online', label: 'Online' },
  { key: 'disabled', label: 'Отключённые' },
];

const ACTION_TEXT = {
  restart: { title: 'Перезапустить ноду', confirm: 'Перезапустить', done: 'Нода перезапускается' },
  enable: { title: 'Включить ноду', confirm: 'Включить', done: 'Нода включена' },
  disable: { title: 'Отключить ноду', confirm: 'Отключить', done: 'Нода отключена' },
};

export default function Nodes() {
  const toast = useToast();
  const { data, setData, error, loading, reload } = usePolling(nodesApi.list, 15000);
  const [refreshing, setRefreshing] = useState(false);
  const [filter, setFilter] = useState('all');
  const [query, setQuery] = useState('');
  const [confirm, setConfirm] = useState(null); // {node, action}
  const [busy, setBusy] = useState(false);

  const counts = useMemo(() => {
    const c = { all: 0, online: 0, offline: 0, disabled: 0 };
    (data || []).forEach((n) => {
      c.all += 1;
      c[nodeState(n).key] += 1;
    });
    return c;
  }, [data]);

  const list = useMemo(() => {
    const q = query.trim().toLowerCase();
    return (data || [])
      .filter((n) => filter === 'all' || nodeState(n).key === filter)
      .filter((n) => !q || n.name.toLowerCase().includes(q) || n.address.toLowerCase().includes(q))
      .sort((a, b) => {
        const order = { offline: 0, online: 1, disabled: 2 };
        return order[nodeState(a).key] - order[nodeState(b).key] || a.name.localeCompare(b.name);
      });
  }, [data, filter, query]);

  const refresh = async () => {
    setRefreshing(true);
    try {
      setData(await nodesApi.refresh());
    } catch (e) {
      toast.error(e.message);
    } finally {
      setRefreshing(false);
    }
  };

  const doAction = async () => {
    setBusy(true);
    try {
      await nodesApi.action(confirm.node.uuid, confirm.action);
      toast.success(ACTION_TEXT[confirm.action].done);
      setConfirm(null);
      setTimeout(refresh, 2000);
    } catch (e) {
      toast.error(e.message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="page">
      <PageHeader
        title="Ноды"
        subtitle={data ? `Online ${counts.online} из ${counts.online + counts.offline}` : ''}
        actions={
          <button type="button" className="btn btn--primary" onClick={refresh} disabled={refreshing}>
            {refreshing ? <Spinner size={16} /> : <IconRefresh size={18} />}
            <span>Обновить</span>
          </button>
        }
      />

      <div className="toolbar">
        <div className="search">
          <IconSearch size={18} />
          <input
            className="input"
            placeholder="Поиск по имени или адресу"
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
              <span className="chip__count">{counts[f.key]}</span>
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
          title={data?.length ? 'Ничего не найдено' : 'Нод пока нет'}
          text={data?.length ? '' : 'Данные подтянутся из Remnawave после первого опроса'}
        />
      ) : (
        <div className="node-grid">
          {list.map((n) => {
            const st = nodeState(n);
            return (
              <article key={n.uuid} className={`card node-card node-card--${st.key}`}>
                <div className="node-card__head">
                  <div className="node-card__title">
                    {n.country_code && <span className="node-card__cc">{n.country_code}</span>}
                    <span className="node-card__name">{n.name}</span>
                  </div>
                  <Badge tone={st.tone}>{st.label}</Badge>
                </div>

                <div className="node-card__addr mono">
                  {n.address}
                  {n.port ? `:${n.port}` : ''}
                </div>

                {st.key === 'online' && (
                  <div className={`node-speed ${n.speed_drop_since ? 'is-drop' : ''}`}>
                    <div>
                      <span className="muted small">Скорость</span>
                      <b>{formatSpeed(n.speed_bps)}</b>
                    </div>
                    <div>
                      <span className="muted small">Норма</span>
                      <span>{n.baseline_bps === null ? 'набирается…' : formatSpeed(n.baseline_bps)}</span>
                    </div>
                    {n.speed_drop_since && (
                      <span className="node-speed__flag">↓ падение {formatDuration(n.speed_drop_since)}</span>
                    )}
                  </div>
                )}

                <dl className="node-card__meta">
                  <div>
                    <dt>Онлайн</dt>
                    <dd>{n.users_online ?? '—'}</dd>
                  </div>
                  <div>
                    <dt>Xray</dt>
                    <dd>{n.xray_version || '—'}</dd>
                  </div>
                  <div>
                    <dt>{st.key === 'offline' ? 'Не работает' : 'Обновлено'}</dt>
                    <dd>
                      {st.key === 'offline' && n.offline_since
                        ? formatDuration(n.offline_since)
                        : formatRelative(n.updated_at)}
                    </dd>
                  </div>
                </dl>

                {n.domain_id && (
                  <Link to={`/domains/${n.domain_id}`} className="node-card__domain">
                    <span>Домен</span>
                    <DomainStatusBadge status={n.domain_status} />
                  </Link>
                )}

                {st.key === 'offline' && n.last_status_message && (
                  <p className="node-card__msg">{n.last_status_message}</p>
                )}

                <div className="node-card__actions">
                  <button
                    type="button"
                    className="btn btn--sm btn--ghost"
                    disabled={n.is_disabled}
                    onClick={() => setConfirm({ node: n, action: 'restart' })}
                  >
                    <IconRefresh size={16} />
                    <span>Рестарт</span>
                  </button>
                  <button
                    type="button"
                    className={`btn btn--sm btn--ghost ${n.is_disabled ? '' : 'btn--danger-text'}`}
                    onClick={() => setConfirm({ node: n, action: n.is_disabled ? 'enable' : 'disable' })}
                  >
                    <IconPower size={16} />
                    <span>{n.is_disabled ? 'Включить' : 'Отключить'}</span>
                  </button>
                </div>
              </article>
            );
          })}
        </div>
      )}

      {confirm && (
        <ConfirmModal
          title={ACTION_TEXT[confirm.action].title}
          text={
            <>
              {ACTION_TEXT[confirm.action].title} <b>{confirm.node.name}</b> ({confirm.node.address})?
            </>
          }
          confirmText={ACTION_TEXT[confirm.action].confirm}
          danger={confirm.action === 'disable'}
          busy={busy}
          onConfirm={doAction}
          onClose={() => setConfirm(null)}
        />
      )}
    </div>
  );
}
