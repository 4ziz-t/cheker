import { useCallback, useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { domainsApi, eventsApi, investigationsApi } from '../api/index.js';
import Badge, { DomainStatusBadge } from '../components/Badge.jsx';
import EventItem from '../components/EventItem.jsx';
import InvestigationList from '../components/InvestigationList.jsx';
import {
  IconArrowLeft,
  IconDown,
  IconEdit,
  IconPlus,
  IconRefresh,
  IconSwap,
  IconTrash,
  IconUp,
} from '../components/Icons.jsx';
import Modal, { ConfirmModal } from '../components/Modal.jsx';
import PageHeader, { EmptyState, ErrorBox } from '../components/PageHeader.jsx';
import Spinner from '../components/Spinner.jsx';
import { useToast } from '../components/Toast.jsx';
import Toggle from '../components/Toggle.jsx';
import usePolling from '../hooks/usePolling.js';
import { describeCheck, formatDateTime, formatRelative, ipState, isIPv4, parseIpList } from '../utils/format.js';
import '../styles/domains.css';

function IpDetails({ ip }) {
  const details = ip.details || {};
  const lines = Object.entries(details).map(([name, d]) => describeCheck(name, d));
  if (!lines.length) return null;
  return (
    <div className="ip-row__details">
      {lines.map((l) => (
        <span key={l}>{l}</span>
      ))}
    </div>
  );
}

function BulkEditModal({ ips, onClose, onSave }) {
  const [text, setText] = useState(ips.map((i) => i.ip).join('\n'));
  const [busy, setBusy] = useState(false);
  const { valid, invalid } = parseIpList(text);

  const save = async () => {
    setBusy(true);
    try {
      await onSave(valid);
      onClose();
    } finally {
      setBusy(false);
    }
  };

  return (
    <Modal
      title="Список IP"
      onClose={onClose}
      footer={
        <>
          <button type="button" className="btn btn--ghost" onClick={onClose}>
            Отмена
          </button>
          <button type="button" className="btn btn--primary" onClick={save} disabled={busy || invalid.length > 0}>
            {busy ? 'Сохраняю…' : 'Сохранить'}
          </button>
        </>
      }
    >
      <div className="form">
        <textarea
          className="input mono"
          rows={10}
          value={text}
          onChange={(e) => setText(e.target.value)}
          spellCheck={false}
        />
        <span className="field__hint">
          Порядок строк = порядок переключения. Распознано: {valid.length}
          {invalid.length > 0 && <span className="text-bad"> · ошибочные: {invalid.join(', ')}</span>}
        </span>
      </div>
    </Modal>
  );
}

export default function DomainDetail() {
  const { id } = useParams();
  const navigate = useNavigate();
  const toast = useToast();

  const loadDomain = useCallback(() => domainsApi.get(id), [id]);
  const { data: domain, setData: setDomain, error, loading, reload } = usePolling(loadDomain, 20000, [id]);

  const loadEvents = useCallback(
    () => (domain ? eventsApi.list({ domain: domain.name, limit: 20 }) : Promise.resolve(null)),
    [domain?.name],
  );
  const { data: events, reload: reloadEvents } = usePolling(loadEvents, 30000, [domain?.name]);

  const loadInvestigations = useCallback(() => investigationsApi.list({ domain_id: id, limit: 5 }), [id]);
  const { data: investigations, reload: reloadInvestigations } = usePolling(loadInvestigations, 20000, [id]);
  const [startingInv, setStartingInv] = useState(false);

  const [checking, setChecking] = useState(false);
  const [newIp, setNewIp] = useState('');
  const [bulk, setBulk] = useState(false);
  const [confirm, setConfirm] = useState(null); // {kind, ip}
  const [busy, setBusy] = useState(false);
  const [notes, setNotes] = useState(null);
  const [port, setPort] = useState(null);
  const [checkingIp, setCheckingIp] = useState('');

  if (loading && !domain) {
    return (
      <div className="page-loading">
        <Spinner size={28} />
      </div>
    );
  }
  if (!domain) {
    return (
      <div className="page">
        <ErrorBox error={error || new Error('Домен не найден')} onRetry={reload} />
        <Link to="/domains" className="btn btn--ghost">
          К списку доменов
        </Link>
      </div>
    );
  }

  const apply = (updated) => {
    setDomain(updated);
    reloadEvents();
  };

  const run = async (fn, okText) => {
    setBusy(true);
    try {
      const res = await fn();
      if (res) apply(res);
      if (okText) toast.success(okText);
      return true;
    } catch (e) {
      toast.error(e.message);
      return false;
    } finally {
      setBusy(false);
    }
  };

  const ipList = domain.ips.map((i) => i.ip);
  const saveIps = (ips, okText) => run(() => domainsApi.setIps(domain.id, ips), okText);

  const move = (index, dir) => {
    const next = [...ipList];
    const target = index + dir;
    if (target < 0 || target >= next.length) return;
    [next[index], next[target]] = [next[target], next[index]];
    saveIps(next);
  };

  const addIp = async (e) => {
    e.preventDefault();
    const ip = newIp.trim();
    if (!isIPv4(ip)) {
      toast.error('Некорректный IPv4');
      return;
    }
    if (ipList.includes(ip)) {
      toast.error('Этот IP уже в списке');
      return;
    }
    if (await saveIps([...ipList, ip], `IP ${ip} добавлен`)) setNewIp('');
  };

  const checkNow = async () => {
    setChecking(true);
    try {
      apply(await domainsApi.check(domain.id));
      toast.success('Проверка завершена');
    } catch (e) {
      toast.error(e.message);
    } finally {
      setChecking(false);
    }
  };

  const doConfirm = async () => {
    const { kind, ip } = confirm;
    let ok = true;
    if (kind === 'switch') {
      ok = await run(() => domainsApi.switchIp(domain.id, ip), `A-запись изменена на ${ip}`);
    } else if (kind === 'remove') {
      ok = await saveIps(ipList.filter((x) => x !== ip), `IP ${ip} удалён`);
    } else if (kind === 'delete') {
      setBusy(true);
      try {
        await domainsApi.remove(domain.id);
        toast.success(`Домен ${domain.name} удалён`);
        navigate('/domains');
        return;
      } catch (e) {
        toast.error(e.message);
        ok = false;
      } finally {
        setBusy(false);
      }
    }
    if (ok) setConfirm(null);
  };

  const confirmProps = (() => {
    if (!confirm) return null;
    const entry = domain.ips.find((i) => i.ip === confirm.ip);
    if (confirm.kind === 'switch') {
      return {
        title: 'Сменить IP вручную',
        text: (
          <>
            A-запись <b>{domain.name}</b> будет изменена с <span className="mono">{domain.current_ip || '—'}</span> на{' '}
            <span className="mono">{confirm.ip}</span>.
            {entry?.is_blocked && <span className="text-bad"> Внимание: этот IP числится в бане.</span>}
          </>
        ),
        confirmText: 'Сменить',
        danger: !!entry?.is_blocked,
      };
    }
    if (confirm.kind === 'remove') {
      return {
        title: 'Удалить IP из списка',
        text: (
          <>
            Удалить <span className="mono">{confirm.ip}</span> из списка?
            {confirm.ip === domain.current_ip && ' Это текущий IP — A-запись в Cloudflare останется без изменений.'}
          </>
        ),
        confirmText: 'Удалить',
        danger: true,
      };
    }
    return {
      title: 'Удалить домен',
      text: (
        <>
          Удалить <b>{domain.name}</b> из мониторинга? Запись в Cloudflare не будет изменена. Из Remnawave он заново не добавится — только вручную.
        </>
      ),
      confirmText: 'Удалить домен',
      danger: true,
    };
  })();

  const notesValue = notes ?? domain.notes;
  const isIpEntry = domain.kind === 'ip';
  const portValue = port ?? (domain.check_port ? String(domain.check_port) : '');
  const portDirty = port !== null && port !== (domain.check_port ? String(domain.check_port) : '');

  const startInvestigation = async () => {
    setStartingInv(true);
    try {
      await investigationsApi.start(domain.id);
      toast.success('Проверка запущена');
      reloadInvestigations();
    } catch (e) {
      toast.error(e.message);
    } finally {
      setStartingInv(false);
    }
  };

  const checkOne = async (ip) => {
    setCheckingIp(ip);
    try {
      apply(await domainsApi.checkOneIp(domain.id, ip));
      toast.success(`${ip} проверен`);
    } catch (e) {
      toast.error(e.message);
    } finally {
      setCheckingIp('');
    }
  };

  const savePort = async () => {
    const value = port.trim() === '' ? null : Number(port);
    if (value !== null && (!Number.isInteger(value) || value < 1 || value > 65535)) {
      toast.error('Порт должен быть от 1 до 65535');
      return;
    }
    if (await run(() => domainsApi.update(domain.id, { check_port: value }), 'Порт сохранён')) setPort(null);
  };

  return (
    <div className="page">
      <PageHeader
        back={
          <Link to="/domains" className="icon-btn" aria-label="Назад">
            <IconArrowLeft />
          </Link>
        }
        title={<span className="mono-title">{domain.name}</span>}
        subtitle={`Проверен ${formatRelative(domain.last_checked_at)}`}
        actions={
          <>
            <button type="button" className="btn btn--primary" onClick={checkNow} disabled={checking}>
              {checking ? <Spinner size={16} /> : <IconRefresh size={18} />}
              <span>Проверить</span>
            </button>
            <button
              type="button"
              className="btn btn--ghost btn--danger-text"
              onClick={() => setConfirm({ kind: 'delete' })}
            >
              <IconTrash size={18} />
              <span>Удалить</span>
            </button>
          </>
        }
      />

      <ErrorBox error={error} onRetry={reload} />

      <div className="detail-grid">
        <section className="card panel summary">
          {(isIpEntry || domain.source === 'remnawave') && (
            <div className="domain-card__tags">
              {isIpEntry && <span className="tag">IP-адрес</span>}
              {domain.source === 'remnawave' && <span className="tag tag--muted">добавлен из Remnawave</span>}
            </div>
          )}
          <div className="summary__status">
            {domain.enabled ? <DomainStatusBadge status={domain.status} /> : <Badge>Мониторинг выключен</Badge>}
            {domain.status_message && <span className="muted">{domain.status_message}</span>}
          </div>
          <div className="summary__ip">
            <span className="muted small">Текущий IP (A-запись)</span>
            <span className="mono summary__ip-value">{domain.current_ip || '—'}</span>
          </div>
          <dl className="summary__meta">
            <div>
              <dt>Последняя проверка</dt>
              <dd>{formatDateTime(domain.last_checked_at)}</dd>
            </div>
            <div>
              <dt>Последняя смена IP</dt>
              <dd>{formatDateTime(domain.last_switch_at)}</dd>
            </div>
            <div>
              <dt>Ноды Remnawave</dt>
              <dd>{domain.nodes.length ? domain.nodes.join(', ') : '—'}</dd>
            </div>
          </dl>
          <div className="summary__toggles">
            <Toggle
              checked={domain.enabled}
              disabled={busy}
              onChange={(v) => run(() => domainsApi.update(domain.id, { enabled: v }), v ? 'Мониторинг включён' : 'Мониторинг выключен')}
              label="Мониторинг"
              hint="Проверять домен по расписанию"
            />
            {isIpEntry ? (
              <span className="field__hint">
                Это IP-адрес, а не домен: при бане придёт уведомление, но сменить его автоматически нельзя.
              </span>
            ) : (
              <Toggle
                checked={domain.auto_switch}
                disabled={busy}
                onChange={(v) => run(() => domainsApi.update(domain.id, { auto_switch: v }), v ? 'Автосмена включена' : 'Автосмена выключена')}
                label="Автосмена IP"
                hint="Менять A-запись при бане"
              />
            )}
            <div className="field">
              <span className="field__label">Порт для проверки в Latency Lab</span>
              <div className="port-field">
                <input
                  className="input"
                  type="number"
                  min={1}
                  max={65535}
                  placeholder="общий"
                  value={portValue}
                  onChange={(e) => setPort(e.target.value)}
                />
                {portDirty && (
                  <button type="button" className="btn btn--sm btn--primary" disabled={busy} onClick={savePort}>
                    Сохранить
                  </button>
                )}
              </div>
              <span className="field__hint">Пусто — порт из общих настроек (Настройки → Источники)</span>
            </div>
          </div>
        </section>

        <section className="card panel">
          <div className="panel__head">
            <h2 className="panel__title">{isIpEntry ? 'Проверка IP' : `IP-адреса · ${domain.ips.length}`}</h2>
            {!isIpEntry && (
              <button type="button" className="btn btn--sm btn--ghost" onClick={() => setBulk(true)}>
                <IconEdit size={16} />
                <span>Списком</span>
              </button>
            )}
          </div>

          {!isIpEntry && domain.ips.length > 1 && (
            <p className="field__hint">
              Резервные IP проверяются, только когда нужно переключиться (или кнопкой ↻). Каждая проверка — 1 запрос
              Latency Lab.
            </p>
          )}
          {domain.ips.length === 0 ? (
            <EmptyState title="Список пуст" text="Добавьте IP, на которые можно переключать домен" />
          ) : (
            <ol className="ip-list">
              {domain.ips.map((ip, index) => {
                const state = ipState(ip);
                const isCurrent = ip.ip === domain.current_ip;
                return (
                  <li key={ip.id} className={`ip-row ${isCurrent ? 'is-current' : ''}`}>
                    <span className="ip-row__pos">{index + 1}</span>
                    <div className="ip-row__main">
                      <div className="ip-row__top">
                        <span className="mono ip-row__ip">{ip.ip}</span>
                        {isCurrent && <span className="tag">текущий</span>}
                        <Badge tone={state.tone}>{state.label}</Badge>
                      </div>
                      <span className="muted small">
                        {ip.last_checked_at ? `проверен ${formatRelative(ip.last_checked_at)}` : 'ещё не проверялся'}
                        {ip.blocked_since && ` · в бане с ${formatDateTime(ip.blocked_since)}`}
                      </span>
                      <IpDetails ip={ip} />
                    </div>
                    {!isIpEntry && <div className="ip-row__actions">
                      {!isCurrent && (
                        <button
                          type="button"
                          className="btn btn--sm btn--ghost"
                          disabled={busy}
                          onClick={() => setConfirm({ kind: 'switch', ip: ip.ip })}
                          title="Назначить этот IP в A-запись"
                        >
                          <IconSwap size={16} />
                          <span>Назначить</span>
                        </button>
                      )}
                      <button
                        type="button"
                        className="icon-btn"
                        disabled={busy || !!checkingIp}
                        onClick={() => checkOne(ip.ip)}
                        aria-label="Проверить этот IP"
                        title="Проверить этот IP сейчас (1 запрос к источникам)"
                      >
                        {checkingIp === ip.ip ? <Spinner size={16} /> : <IconRefresh size={18} />}
                      </button>
                      <button
                        type="button"
                        className="icon-btn"
                        disabled={busy || index === 0}
                        onClick={() => move(index, -1)}
                        aria-label="Выше"
                      >
                        <IconUp size={18} />
                      </button>
                      <button
                        type="button"
                        className="icon-btn"
                        disabled={busy || index === domain.ips.length - 1}
                        onClick={() => move(index, 1)}
                        aria-label="Ниже"
                      >
                        <IconDown size={18} />
                      </button>
                      <button
                        type="button"
                        className="icon-btn icon-btn--danger"
                        disabled={busy}
                        onClick={() => setConfirm({ kind: 'remove', ip: ip.ip })}
                        aria-label="Удалить"
                      >
                        <IconTrash size={18} />
                      </button>
                    </div>}
                  </li>
                );
              })}
            </ol>
          )}

          {!isIpEntry && (
          <form className="add-ip" onSubmit={addIp}>
            <input
              className="input mono"
              placeholder="Новый IP, например 1.2.3.4"
              value={newIp}
              onChange={(e) => setNewIp(e.target.value)}
              inputMode="decimal"
            />
            <button type="submit" className="btn btn--primary" disabled={busy || !newIp.trim()}>
              <IconPlus size={18} />
              <span>Добавить</span>
            </button>
          </form>
          )}
        </section>

        <section className="card panel">
          <div className="panel__head">
            <h2 className="panel__title">Проверка после падения скорости</h2>
            <button
              type="button"
              className="btn btn--sm btn--ghost"
              disabled={startingInv || investigations?.some((i) => i.status === 'active')}
              onClick={startInvestigation}
              title="Проверить IP несколько раз с интервалом, как при падении скорости ноды"
            >
              {startingInv ? <Spinner size={14} /> : <IconRefresh size={16} />}
              <span>Запустить</span>
            </button>
          </div>
          {!investigations?.length ? (
            <EmptyState
              title="Проверок не было"
              text={
                domain.nodes.length
                  ? 'Запустится сама, когда у ноды упадёт скорость'
                  : 'К домену не привязана нода — автоматически не проверяется'
              }
            />
          ) : (
            <InvestigationList
              items={investigations}
              showDomain={false}
              onChanged={() => {
                reloadInvestigations();
                reload();
              }}
            />
          )}
        </section>

        <section className="card panel">
          <h2 className="panel__title">Заметки</h2>
          <textarea
            className="input"
            rows={3}
            placeholder="Например: хостер, срок оплаты, для каких нод"
            value={notesValue}
            onChange={(e) => setNotes(e.target.value)}
          />
          {notes !== null && notes !== domain.notes && (
            <div className="row-end">
              <button
                type="button"
                className="btn btn--sm btn--primary"
                disabled={busy}
                onClick={async () => {
                  if (await run(() => domainsApi.update(domain.id, { notes }), 'Заметки сохранены')) setNotes(null);
                }}
              >
                Сохранить
              </button>
            </div>
          )}
        </section>

        <section className="card panel">
          <h2 className="panel__title">История</h2>
          {!events?.items?.length ? (
            <EmptyState title="Событий пока нет" />
          ) : (
            <ul className="event-list">
              {events.items.map((e) => (
                <EventItem key={e.id} event={e} />
              ))}
            </ul>
          )}
        </section>
      </div>

      {bulk && (
        <BulkEditModal
          ips={domain.ips}
          onClose={() => setBulk(false)}
          onSave={(ips) => saveIps(ips, 'Список IP сохранён')}
        />
      )}

      {confirmProps && (
        <ConfirmModal {...confirmProps} busy={busy} onConfirm={doConfirm} onClose={() => setConfirm(null)} />
      )}
    </div>
  );
}
