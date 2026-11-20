import { useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import { nodesApi } from '../api/index.js';
import Badge, { DomainStatusBadge } from '../components/Badge.jsx';
import { IconRefresh, IconSearch, IconSwap, IconTrash } from '../components/Icons.jsx';
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


export default function Nodes() {
  const toast = useToast();
  const { data, setData, error, loading, reload } = usePolling(nodesApi.list, 15000);
  const [refreshing, setRefreshing] = useState(false);
  const [syncing, setSyncing] = useState(false);
  const [toDelete, setToDelete] = useState(null);
  const [deleting, setDeleting] = useState(false);
  const [filter, setFilter] = useState('all');
  const [query, setQuery] = useState('');

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

  const sync = async () => {
    setSyncing(true);
    try {
      const res = await nodesApi.sync();
      setData(res.nodes);
      toast.success(
        res.restored ? `Возвращено нод: ${res.restored} (вместе с их доменами/IP)` : 'Синхронизировано, удалённых нод не было',
      );
    } catch (e) {
      toast.error(e.message);
    } finally {
      setSyncing(false);
    }
  };

  const doDelete = async () => {
    setDeleting(true);
    try {
      const res = await nodesApi.remove(toDelete.uuid);
      setData((prev) => prev.filter((n) => n.uuid !== toDelete.uuid));
      toast.success(
        res.deleted_domain ? `Нода и домен ${res.deleted_domain} удалены из Cheker` : 'Нода удалена из Cheker',
      );
      setToDelete(null);
    } catch (e) {
      toast.error(e.message);
    } finally {
      setDeleting(false);
    }
  };


  return (
    <div className="page">
      <PageHeader
        title="Ноды"
        subtitle={data ? `Online ${counts.online} из ${counts.online + counts.offline}` : ''}
        actions={
          <>
            <button
              type="button"
              className="btn btn--primary"
              onClick={refresh}
              disabled={refreshing || syncing}
              title="Обновить статус и скорость нод из списка"
            >
              {refreshing ? <Spinner size={16} /> : <IconRefresh size={18} />}
              <span>Обновить</span>
            </button>
            <button
              type="button"
              className="btn btn--ghost"
              onClick={sync}
              disabled={refreshing || syncing}
              title="Вернуть удалённые из списка ноды и их домены/IP"
            >
              {syncing ? <Spinner size={16} /> : <IconSwap size={18} />}
              <span>Синхронизировать с Remnawave</span>
            </button>
          </>
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
                  <div className="node-card__head-actions">
                    <Badge tone={st.tone}>{st.label}</Badge>
                    <button
                      type="button"
                      className="icon-btn icon-btn--danger"
                      title="Удалить ноду из Cheker"
                      aria-label="Удалить ноду"
                      onClick={() => setToDelete(n)}
                    >
                      <IconTrash size={17} />
                    </button>
                  </div>
                </div>

                <div className="node-card__addr mono">
                  {n.address}
                  {n.port ? `:${n.port}` : ''}
                </div>

                {st.key !== 'disabled' && (
                  <div className={`node-speed ${n.speed_drop_since ? 'is-drop' : ''}`}>
                    {st.key === 'online' ? (
                      <>
                        <div>
                          <span className="muted small">Сейчас</span>
                          <b>{n.speed_now_bps == null ? '…' : formatSpeed(n.speed_now_bps)}</b>
                        </div>
                        <div>
                          <span className="muted small">Среднее</span>
                          <span>{n.speed_bps == null ? 'считается…' : formatSpeed(n.speed_bps)}</span>
                        </div>
                        <div>
                          <span className="muted small">Норма</span>
                          <span>{n.baseline_bps == null ? 'набирается…' : formatSpeed(n.baseline_bps)}</span>
                        </div>
                        {n.speed_drop_since && (
                          <span className="node-speed__flag">↓ падение {formatDuration(n.speed_drop_since)}</span>
                        )}
                      </>
                    ) : (
                      <div>
                        <span className="muted small">Скорость</span>
                        <b className="text-bad">0 — нода offline</b>
                      </div>
                    )}
                  </div>
                )}
                {st.key === 'online' && !n.speed_source && (
                  <p className="field__hint">Remnawave не отдаёт трафик этой ноды — скорость посчитать нельзя</p>
                )}

                <dl className="node-card__meta">
                  <div>
                    <dt>Онлайн</dt>
                    <dd>{n.users_online ?? '—'}</dd>
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

              </article>
            );
          })}
        </div>
      )}

      {toDelete && (
        <ConfirmModal
          title="Удалить ноду из Cheker"
          text={
            <>
              Нода <b>{toDelete.name}</b> ({toDelete.address}) пропадёт из списка, её статус и скорость перестанут
              отслеживаться.
              {toDelete.domain_id && (
                <>
                  {' '}
                  Вместе с ней удалится домен/IP <b className="mono">{toDelete.address}</b> из вкладки «Домены».
                </>
              )}{' '}
              В Remnawave ничего не изменится. Вернуть можно кнопкой «Синхронизировать с Remnawave».
            </>
          }
          confirmText="Удалить"
          danger
          busy={deleting}
          onConfirm={doDelete}
          onClose={() => setToDelete(null)}
        />
      )}
    </div>
  );
}
