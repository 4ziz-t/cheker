import { useMemo, useRef, useState } from 'react';
import { flushSync } from 'react-dom';
import { Link } from 'react-router-dom';
import { domainsApi, nodesApi } from '../api/index.js';
import Badge, { DomainStatusBadge } from '../components/Badge.jsx';
import { IconChevronRight, IconGrip, IconRefresh, IconSearch, IconSwap, IconTrash } from '../components/Icons.jsx';
import { ConfirmModal } from '../components/Modal.jsx';
import IpMeter from '../components/IpMeter.jsx';
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
  const [dragging, setDragging] = useState(null); // uuid ноды, которую тянут
  const [checkingIps, setCheckingIps] = useState(() => new Set()); // id доменов, у которых идёт проверка IP
  const [savingOrder, setSavingOrder] = useState(false);

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
    // порядок — как пришёл с сервера (его задаёт пользователь перетаскиванием)
    return (data || [])
      .filter((n) => filter === 'all' || nodeState(n).key === filter)
      .filter((n) => !q || n.name.toLowerCase().includes(q) || n.address.toLowerCase().includes(q));
  }, [data, filter, query]);

  const canReorder = filter === 'all' && !query.trim() && list.length > 1;

  const saveOrder = async (ids) => {
    setSavingOrder(true);
    try {
      setData(await nodesApi.saveOrder(ids));
    } catch (err) {
      toast.error(`Не удалось сохранить порядок: ${err.message}`);
      reload();
    } finally {
      setSavingOrder(false);
    }
  };

  // ---------- перетаскивание (мышь и палец: pointer events) ----------
  // Пока карточку тянут, список НЕ перестраивается: карточка едет за курсором,
  // а соседние плавно сдвигаются, освобождая место. Порядок меняется только при отпускании.
  const listRef = useRef(null);
  const dragRef = useRef(null);

  const rowEls = () => (listRef.current ? [...listRef.current.querySelectorAll('[data-uuid]')] : []);

  const layout = (drag, pointerY) => {
    const { rects, index, step } = drag;
    const dy = pointerY - drag.startY;
    const center = rects[index].top + rects[index].height / 2 + dy;
    let target = 0;
    rects.forEach((r, j) => {
      if (j !== index && r.top + r.height / 2 < center) target += 1;
    });
    drag.target = target;
    drag.els.forEach((el, j) => {
      if (j === index) {
        el.style.transform = `translateY(${dy}px)`;
        return;
      }
      let shift = 0;
      if (index < j && j <= target) shift = -step;
      else if (target <= j && j < index) shift = step;
      el.style.transform = shift ? `translateY(${shift}px)` : '';
    });
  };

  const onGripDown = (e, uuid) => {
    if (!canReorder || savingOrder || (e.pointerType === 'mouse' && e.button !== 0)) return;
    e.preventDefault();
    e.currentTarget.setPointerCapture?.(e.pointerId);
    const els = rowEls();
    const index = els.findIndex((el) => el.dataset.uuid === uuid);
    if (index < 0) return;
    const rects = els.map((el) => {
      const r = el.getBoundingClientRect();
      return { top: r.top + window.scrollY, height: r.height };
    });
    const gap = rects.length > 1 ? rects[1].top - (rects[0].top + rects[0].height) : 8;
    dragRef.current = {
      uuid,
      pointerId: e.pointerId,
      els,
      rects,
      index,
      target: index,
      step: rects[index].height + gap,
      startY: e.clientY + window.scrollY,
    };
    setDragging(uuid);
  };

  const onGripMove = (e) => {
    const drag = dragRef.current;
    if (!drag || drag.pointerId !== e.pointerId) return;
    // автопрокрутка у краёв экрана
    if (e.clientY < 70) window.scrollBy(0, -14);
    else if (e.clientY > window.innerHeight - 70) window.scrollBy(0, 14);
    layout(drag, e.clientY + window.scrollY);
  };

  const onGripUp = (e) => {
    const drag = dragRef.current;
    if (!drag || drag.pointerId !== e.pointerId) return;
    dragRef.current = null;
    const ids = (data || []).map((n) => n.uuid);
    const moved = drag.target !== drag.index;
    if (moved) {
      ids.splice(drag.index, 1);
      ids.splice(drag.target, 0, drag.uuid);
      const byId = new Map(data.map((n) => [n.uuid, n]));
      // сразу перестраиваем список и снимаем сдвиги — без «прыжка» карточек
      flushSync(() => {
        setData(ids.map((u) => byId.get(u)));
        setDragging(null);
      });
    } else {
      flushSync(() => setDragging(null));
    }
    drag.els.forEach((el) => {
      el.style.transform = '';
    });
    if (moved) saveOrder(ids);
  };

  // перемещение стрелками ↑/↓ (клавиатура)
  const moveBy = (uuid, delta) => {
    const ids = (data || []).map((n) => n.uuid);
    const i = ids.indexOf(uuid);
    const j = i + delta;
    if (i < 0 || j < 0 || j >= ids.length) return;
    [ids[i], ids[j]] = [ids[j], ids[i]];
    const byId = new Map(data.map((n) => [n.uuid, n]));
    setData(ids.map((u) => byId.get(u)));
    saveOrder(ids);
  };

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
        res.restored
          ? `Возвращено нод: ${res.restored} (вместе с их доменами/IP). Порядок — как в Remnawave`
          : 'Синхронизировано: порядок нод как в Remnawave',
      );
    } catch (e) {
      toast.error(e.message);
    } finally {
      setSyncing(false);
    }
  };

  // ↻ у колонки «IP»: проверить все IP домена ноды (текущий и резервные)
  const checkIps = async (n) => {
    setCheckingIps((prev) => new Set(prev).add(n.domain_id));
    try {
      const d = await domainsApi.checkAllIps(n.domain_id);
      const ok = d.ips.filter((i) => i.is_blocked === false).length;
      const banned = d.ips.filter((i) => i.is_blocked === true).length;
      const unknown = d.ips.length - ok - banned;
      const parts = [`в порядке ${ok} из ${d.ips.length}`];
      if (banned) parts.push(`в бане ${banned}`);
      if (unknown) parts.push(`не удалось проверить ${unknown}`);
      (banned ? toast.error : toast.success)(`${n.name}: ${parts.join(', ')}`);
      await reload();
    } catch (e) {
      toast.error(`${n.name}: ${e.message}`);
    } finally {
      setCheckingIps((prev) => {
        const next = new Set(prev);
        next.delete(n.domain_id);
        return next;
      });
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
        <div className={`node-list ${dragging ? 'is-sorting' : ''}`} ref={listRef}>
          <div className="node-row node-row--head" aria-hidden="true">
            <span />
            <span>Нода</span>
            <span>Статус</span>
            <span>Сейчас</span>
            <span>IP</span>
            <span>Онлайн</span>
            <span>Обновлено</span>
            <span>Домен</span>
            <span />
          </div>
          {list.map((n) => {
            const st = nodeState(n);
            const online = st.key === 'online';
            const noSpeed = online && !n.speed_source;
            return (
              <div
                key={n.uuid}
                data-uuid={n.uuid}
                className={`card node-row node-row--${st.key} ${n.speed_drop_since ? 'is-drop' : ''} ${
                  dragging === n.uuid ? 'is-dragging' : ''
                }`}
              >
                <div className="node-row__grip-cell">
                  <button
                    type="button"
                    className="node-row__grip"
                    title={canReorder ? 'Потяните, чтобы переместить' : 'Сбросьте фильтр и поиск, чтобы менять порядок'}
                    aria-label="Переместить ноду"
                    disabled={!canReorder || savingOrder}
                    onPointerDown={(e) => onGripDown(e, n.uuid)}
                    onPointerMove={onGripMove}
                    onPointerUp={onGripUp}
                    onPointerCancel={onGripUp}
                    onKeyDown={(e) => {
                      if (!canReorder) return;
                      if (e.key === 'ArrowUp') {
                        e.preventDefault();
                        moveBy(n.uuid, -1);
                      } else if (e.key === 'ArrowDown') {
                        e.preventDefault();
                        moveBy(n.uuid, 1);
                      }
                    }}
                  >
                    <IconGrip size={18} />
                  </button>
                </div>
                <div className="node-row__main">
                  <div className="node-row__title">
                    {n.country_code && <span className="node-row__cc">{n.country_code}</span>}
                    <span className="node-row__name">{n.name}</span>
                  </div>
                  <div className="node-row__addr mono">
                    {n.address}
                    {n.port ? `:${n.port}` : ''}
                  </div>
                  {st.key === 'offline' && n.last_status_message && (
                    <div className="node-row__msg">{n.last_status_message}</div>
                  )}
                  {noSpeed && <div className="node-row__hint">Remnawave не отдаёт трафик — скорость не посчитать</div>}
                </div>

                <div className="node-row__cell node-row__status">
                  <Badge tone={st.tone}>{st.label}</Badge>
                  {n.speed_drop_since && (
                    <span className="node-row__flag">↓ падение {formatDuration(n.speed_drop_since)}</span>
                  )}
                </div>

                <div className="node-row__cells">
                  <div className="node-row__cell" data-label="Сейчас">
                    {online ? (
                      <b className="node-row__speed">{n.speed_now_bps == null ? '…' : formatSpeed(n.speed_now_bps)}</b>
                    ) : st.key === 'offline' ? (
                      <b className="text-bad">0</b>
                    ) : (
                      '—'
                    )}
                  </div>
                  <div className="node-row__cell node-row__cell--ip" data-label="IP">
                    {n.domain_id ? (
                      <span className="node-row__ip">
                        <IpMeter ok={n.ips_ok} total={n.ips_total} blocked={n.ips_blocked} unknown={n.ips_unknown} />
                        <button
                          type="button"
                          className={`icon-btn node-row__recheck ${checkingIps.has(n.domain_id) ? 'is-busy' : ''}`}
                          title={checkingIps.has(n.domain_id) ? 'Проверяю IP…' : 'Проверить все IP на бан'}
                          aria-label="Проверить все IP"
                          disabled={checkingIps.has(n.domain_id)}
                          onClick={() => checkIps(n)}
                        >
                          <IconRefresh size={15} />
                        </button>
                      </span>
                    ) : (
                      <span className="muted">—</span>
                    )}
                  </div>
                  <div className="node-row__cell" data-label="Онлайн">{n.users_online ?? '—'}</div>
                  <div className="node-row__cell" data-label={st.key === 'offline' ? 'Не работает' : 'Обновлено'}>
                    {st.key === 'offline' && n.offline_since
                      ? formatDuration(n.offline_since)
                      : formatRelative(n.updated_at)}
                  </div>
                  <div className="node-row__cell node-row__cell--domain" data-label="Домен">
                    {n.domain_id ? (
                      <Link
                        to={`/domains/${n.domain_id}`}
                        className="row-link"
                        title={`Открыть домен ${n.address}: IP, проверки, история`}
                      >
                        <DomainStatusBadge status={n.domain_status} />
                        <span className="row-link__text">Открыть</span>
                        <IconChevronRight size={16} />
                      </Link>
                    ) : (
                      <span className="muted">—</span>
                    )}
                  </div>
                </div>
                <div className="node-row__actions">
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
