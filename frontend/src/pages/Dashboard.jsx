import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { dashboardApi, settingsApi } from '../api/index.js';
import Badge, { DomainStatusBadge } from '../components/Badge.jsx';
import BschekOperatorPicker, { countCovered } from '../components/BschekOperatorPicker.jsx';
import EventItem from '../components/EventItem.jsx';
import InvestigationList from '../components/InvestigationList.jsx';
import { ConfirmModal } from '../components/Modal.jsx';
import { IconAlert, IconRefresh, IconSearch } from '../components/Icons.jsx';
import PageHeader, { EmptyState, ErrorBox } from '../components/PageHeader.jsx';
import Spinner from '../components/Spinner.jsx';
import { useToast } from '../components/Toast.jsx';
import usePolling from '../hooks/usePolling.js';
import { formatDuration } from '../utils/format.js';
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

const IP_SOURCE = { cloudflare: 'A-запись Cloudflare', dns: 'DNS' };

function Verdict({ result }) {
  if (result.blocked === true) return <Badge tone="bad">В бане</Badge>;
  if (result.blocked === false) return <Badge tone="ok">Доступен</Badge>;
  return <Badge tone="warn">Не удалось проверить</Badge>;
}

function ResultHead({ result }) {
  return (
    <div className="src-result__head">
      <span className="src-result__target">
        {result.domain && (
          <>
            <span className="mono">{result.domain}</span>
            <span className="muted"> → </span>
          </>
        )}
        <span className="mono ip-tool__ip">{result.ip}</span>
        <span className="muted small">
          {' '}
          · порт {result.port}
          {result.domain && ` · IP из: ${IP_SOURCE[result.ip_source] || result.ip_source}`}
        </span>
      </span>
      <Verdict result={result} />
    </div>
  );
}

function LatencyDetails({ d }) {
  return (
    <dl className="src-facts">
      {d.wire_ok !== undefined && d.wire_ok !== null && (
        <div>
          <dt>С провода (wire)</dt>
          <dd className={d.wire_ok ? 'text-ok' : 'text-bad'}>{d.wire_ok ? 'доступен' : 'недоступен'}</dd>
        </div>
      )}
      {d.label && (
        <div>
          <dt>Вердикт</dt>
          <dd>{d.label}</dd>
        </div>
      )}
      {d.method && (
        <div>
          <dt>Метод</dt>
          <dd className="mono">/{d.method}</dd>
        </div>
      )}
      {(d.operators_ok?.length > 0 || d.operators_fail?.length > 0) && (
        <div>
          <dt>Операторы{d.fallback === 'operators' ? ' (wire не пришёл)' : ''}</dt>
          <dd className="src-ops">
            {(d.operators_ok || []).map((o) => (
              <span key={`ok-${o}`} className="src-op src-op--ok">{o}</span>
            ))}
            {(d.operators_fail || []).map((o) => (
              <span key={`f-${o}`} className="src-op src-op--bad">{o}</span>
            ))}
          </dd>
        </div>
      )}
    </dl>
  );
}

function BschekDetails({ d }) {
  const units = d.units || [];
  return (
    <>
      {units.length > 0 && (
        <ul className="unit-list">
          {units.map((u) => (
            <li key={u.op_key} className="unit">
              <span
                className={`dot ${u.reachable === true ? 'dot--ok' : u.reachable === false ? 'dot--bad' : 'dot--off'}`}
              />
              <span className="unit__name">{u.name}</span>
              <span className="muted small">{u.region}</span>
              {u.dpi === 'on' && <span className="chip__count">БС</span>}
              <span className="unit__state">
                {u.reachable === true && 'доступен'}
                {u.reachable === false && <span className="text-bad">недоступен</span>}
                {u.reachable === null && <span className="muted">{u.error || 'нет данных'}</span>}
                {u.tcp && <span className="muted small"> · TCP {u.tcp}</span>}
              </span>
            </li>
          ))}
        </ul>
      )}
      {d.cost_credits ? <p className="muted small">Списано: {(d.cost_credits / 100).toFixed(2)} ₽</p> : null}
    </>
  );
}

/** Состояние одной кнопки проверки: busy / result / error */
function useCheck() {
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState(null);
  const [error, setError] = useState('');
  const run = async (fn) => {
    setBusy(true);
    setError('');
    setResult(null);
    try {
      setResult(await fn());
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  };
  return { busy, result, error, run };
}

function IpTool() {
  const [target, setTarget] = useState('');
  const [port, setPort] = useState('');
  const latency = useCheck();
  const bschek = useCheck();

  const [units, setUnits] = useState(null);
  const [unitsError, setUnitsError] = useState('');
  const [selected, setSelected] = useState([]);

  useEffect(() => {
    settingsApi
      .bschekUnits()
      .then(setUnits)
      .catch((e) => setUnitsError(e.message));
    settingsApi
      .get()
      .then((s) => setSelected(s.values.bschek_units || []))
      .catch(() => {});
  }, []);

  const value = target.trim();
  const covered = countCovered(units, selected);

  const runLatency = () =>
    latency.run(() => dashboardApi.check({ target: value, checker: 'latencylab', port: port || null }));
  const runBschek = () =>
    bschek.run(() =>
      dashboardApi.check({ target: value, checker: 'bschek', port: port || null, units: selected }),
    );

  return (
    <section className="card panel">
      <h2 className="panel__title">Проверить IP или домен</h2>
      <div className="ip-tool">
        <input
          className="input mono"
          placeholder="1.2.3.4 или de1.example.com"
          value={target}
          onChange={(e) => setTarget(e.target.value)}
          autoCapitalize="none"
          spellCheck={false}
        />
        <input
          className="input mono ip-tool__port"
          placeholder="порт"
          value={port}
          onChange={(e) => setPort(e.target.value.replace(/\D/g, '').slice(0, 5))}
          inputMode="numeric"
          title="Порт для проверки (пусто — из настроек)"
        />
      </div>

      <div className="ip-tool__cols">
        {/* ---------- Latency Lab ---------- */}
        <div className="src-col">
          <div className="src-col__head">
            <span className="src-col__title">Latency Lab</span>
            <span className="muted small">проверка с провода</span>
          </div>
          <button
            type="button"
            className="btn btn--primary"
            disabled={!value || latency.busy}
            onClick={runLatency}
          >
            {latency.busy ? <Spinner size={16} /> : <IconSearch size={18} />}
            <span>{latency.busy ? 'Проверяю…' : 'Проверить в Latency Lab'}</span>
          </button>
          {latency.error && <div className="alert alert--bad">{latency.error}</div>}
          {latency.result && (
            <div className="src-result">
              <ResultHead result={latency.result} />
              {latency.result.error && <p className="src-col__error">{latency.result.error}</p>}
              <LatencyDetails d={latency.result.details || {}} />
            </div>
          )}
        </div>

        {/* ---------- bschekbot ---------- */}
        <div className="src-col">
          <div className="src-col__head">
            <span className="src-col__title">bschekbot</span>
            <span className="muted small">мобильные операторы</span>
          </div>
          {unitsError && <span className="field__hint text-warn">Операторы недоступны: {unitsError}</span>}
          {!units && !unitsError && <Spinner size={16} />}
          {units && <BschekOperatorPicker units={units} value={selected} onChange={setSelected} compact />}
          <span className="field__hint">
            Будет проверено единиц (оператор × округ): <b>{covered}</b> — каждая списывается отдельно.
          </span>
          <button
            type="button"
            className="btn btn--primary"
            disabled={!value || bschek.busy || !selected.length}
            onClick={runBschek}
          >
            {bschek.busy ? <Spinner size={16} /> : <IconSearch size={18} />}
            <span>{bschek.busy ? 'Проверяю…' : 'Проверить в bschekbot'}</span>
          </button>
          {bschek.error && <div className="alert alert--bad">{bschek.error}</div>}
          {bschek.result && (
            <div className="src-result">
              <ResultHead result={bschek.result} />
              {bschek.result.error && <p className="src-col__error">{bschek.result.error}</p>}
              <BschekDetails d={bschek.result.details || {}} />
            </div>
          )}
        </div>
      </div>
      {(latency.busy || bschek.busy) && (
        <p className="field__hint">Проверка может занять до пары минут — источники отвечают не сразу.</p>
      )}
    </section>
  );
}

export default function Dashboard() {
  const toast = useToast();
  const { data, error, loading, reload } = usePolling(dashboardApi.get, 15000);
  const [starting, setStarting] = useState(false);
  const [confirmAll, setConfirmAll] = useState(false);

  const checkNow = async () => {
    setConfirmAll(false);
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
          running
            ? 'Идёт проверка всех доменов…'
            : 'IP доменов проверяются через Latency Lab, когда у ноды падает скорость'
        }
        actions={
          <button
            type="button"
            className="btn btn--ghost"
            onClick={() => setConfirmAll(true)}
            disabled={starting || running}
          >
            {running || starting ? <Spinner size={16} /> : <IconRefresh size={18} />}
            <span>Проверить все домены</span>
          </button>
        }
      />

      <ErrorBox error={error} onRetry={reload} />

      {missing.length > 0 && (
        <div className="alert alert--warn">
          <IconAlert size={18} />
          <span>
            Не настроено: {missing.map(([k]) => INTEGRATION_NAMES[k]).join(', ')} — укажите в «Настройки → Интеграции»
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

          <section className="card panel">
            <div className="panel__head">
              <h2 className="panel__title">Проверки после падения скорости</h2>
            </div>
            {data.investigations.length === 0 ? (
              <EmptyState
                title="Проверок пока не было"
                text="Как только у ноды упадёт скорость, здесь появится проверка IP её домена"
              />
            ) : (
              <InvestigationList items={data.investigations} onChanged={reload} />
            )}
          </section>

          <IpTool />
        </>
      )}
      {confirmAll && (
        <ConfirmModal
          title="Проверить все домены"
          text="Будет проверен текущий IP каждого включённого домена — по 1 запросу Latency Lab на домен. При бане IP сменится сразу, без трёх проверок."
          confirmText="Проверить"
          onConfirm={checkNow}
          onClose={() => setConfirmAll(false)}
        />
      )}
    </div>
  );
}
