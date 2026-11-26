import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { dashboardApi, settingsApi } from '../api/index.js';
import Badge, { DomainStatusBadge } from '../components/Badge.jsx';
import AtlasResult from '../components/AtlasResult.jsx';
import BschekOperatorPicker, { countCovered } from '../components/BschekOperatorPicker.jsx';
import EventItem from '../components/EventItem.jsx';
import InvestigationList from '../components/InvestigationList.jsx';
import { ConfirmModal } from '../components/Modal.jsx';
import {
  IconAlert,
  IconCheck,
  IconChevronRight,
  IconGlobe,
  IconRefresh,
  IconSearch,
  IconServer,
  IconShield,
  IconSwap,
  IconX,
} from '../components/Icons.jsx';
import { onlyLink } from '../components/OnlyBanner.jsx';
import PageHeader, { EmptyState, ErrorBox } from '../components/PageHeader.jsx';
import Spinner from '../components/Spinner.jsx';
import { useToast } from '../components/Toast.jsx';
import usePolling from '../hooks/usePolling.js';
import { DOMAIN_STATUS, formatDuration, formatRelative, formatSpeed } from '../utils/format.js';
import '../styles/dashboard.css';

const INTEGRATION_NAMES = { remnawave: 'Remnawave', cloudflare: 'Cloudflare', telegram: 'Telegram' };

function StatCard({ icon: Icon, label, value, total, tone, hint, to, progress }) {
  const body = (
    <>
      <div className="stat__top">
        <span className={`stat__icon stat__icon--${tone}`}>
          <Icon size={18} />
        </span>
        <span className="stat__label">{label}</span>
        {to && <IconChevronRight size={16} className="stat__chev" />}
      </div>
      <span className={`stat__value stat__value--${tone}`}>
        {value}
        {total !== undefined && <span className="stat__total"> из {total}</span>}
      </span>
      {progress !== undefined && (
        <span className="stat__bar">
          <span className={`stat__bar-fill stat__bar-fill--${tone}`} style={{ width: `${Math.round(progress * 100)}%` }} />
        </span>
      )}
      {hint && <span className="stat__hint">{hint}</span>}
    </>
  );
  return to ? (
    <Link to={to} className={`stat card card--link stat--${tone}`}>
      {body}
    </Link>
  ) : (
    <div className={`stat card stat--${tone}`}>{body}</div>
  );
}

function plural(n, one, few, many) {
  const m10 = n % 10;
  const m100 = n % 100;
  if (m10 === 1 && m100 !== 11) return one;
  if (m10 >= 2 && m10 <= 4 && (m100 < 12 || m100 > 14)) return few;
  return many;
}

/** Общее состояние одной строкой: всё хорошо / нужно внимание / проблемы */
function HealthBanner({ data, running }) {
  const offline = data.nodes.offline.length;
  const hard = data.domains.problems.filter((d) => d.status === 'blocked' || d.status === 'no_ips').length;
  const soft = data.domains.problems.length - hard;
  const drops = data.speeds.filter((n) => n.online && n.drop_since).length;
  const activeInv = data.investigations.filter((i) => i.status === 'active').length;

  const items = [];
  // каждая метка ведёт на список, где показаны только те ноды/домены, к которым она относится
  const isHard = (d) => d.status === 'blocked' || d.status === 'no_ips';
  const invDomains = [...new Set(data.investigations.filter((i) => i.status === 'active').map((i) => i.domain_id))];
  if (offline)
    items.push({
      tone: 'bad',
      text: `${offline} ${plural(offline, 'нода', 'ноды', 'нод')} offline`,
      to: onlyLink('/nodes', data.nodes.offline.map((n) => n.uuid), 'ноды offline'),
    });
  if (hard)
    items.push({
      tone: 'bad',
      text: `${hard} ${plural(hard, 'домен', 'домена', 'доменов')} с IP в бане`,
      to: onlyLink('/domains', data.domains.problems.filter(isHard).map((d) => d.id), 'домены с IP в бане'),
    });
  if (soft)
    items.push({
      tone: 'warn',
      text: `${soft} ${plural(soft, 'домен', 'домена', 'доменов')} с ошибкой`,
      to: onlyLink('/domains', data.domains.problems.filter((d) => !isHard(d)).map((d) => d.id), 'домены с ошибкой'),
    });
  if (drops)
    items.push({
      tone: 'warn',
      text: `падение скорости: ${drops}`,
      to: onlyLink('/nodes', data.speeds.filter((n) => n.online && n.drop_since).map((n) => n.uuid), 'ноды с падением скорости'),
    });
  if (activeInv)
    items.push({
      tone: 'warn',
      text: `идёт проверка IP: ${activeInv}`,
      to: invDomains.length ? onlyLink('/domains', invDomains, 'домены, у которых идёт проверка IP') : undefined,
    });
  if (running) items.push({ tone: 'accent', text: 'идёт проверка всех доменов' });

  const tone = offline || hard ? 'bad' : soft || drops || activeInv ? 'warn' : 'ok';
  const title = { ok: 'Всё работает', warn: 'Нужно внимание', bad: 'Есть проблемы' }[tone];
  const text = {
    ok: `${data.nodes.online} из ${data.nodes.total} нод online, IP доменов не в бане`,
    warn: 'Серьёзных проблем нет, но кое-что стоит проверить',
    bad: 'Посмотрите блок «Требует внимания» ниже',
  }[tone];

  return (
    <section className={`health card health--${tone}`}>
      <span className="health__icon">{tone === 'ok' ? <IconCheck size={26} /> : <IconAlert size={26} />}</span>
      <div className="health__body">
        <h2 className="health__title">{title}</h2>
        <p className="health__text">{text}</p>
        {items.length > 0 && (
          <div className="health__chips">
            {items.map((it) =>
              it.to ? (
                <Link key={it.text} to={it.to} className={`health__chip health__chip--${it.tone}`}>
                  {it.text}
                </Link>
              ) : (
                <span key={it.text} className={`health__chip health__chip--${it.tone}`}>
                  {it.text}
                </span>
              ),
            )}
          </div>
        )}
      </div>
      <div className="health__meta">
        <span>Ноды обновлены</span>
        <b>{formatRelative(data.nodes_updated_at)}</b>
      </div>
    </section>
  );
}

/** Скорость нод: сейчас против нормы */
function SpeedPanel({ speeds }) {
  return (
    <section className="card panel">
      <div className="panel__head">
        <h2 className="panel__title">Скорость нод</h2>
        <Link to="/nodes" className="link-sm">
          Все ноды →
        </Link>
      </div>
      {speeds.length === 0 ? (
        <EmptyState title="Нод пока нет" text="Подключите Remnawave в «Настройки → Интеграции»" />
      ) : (
        <ul className="speed-list">
          {speeds.map((n) => {
            const ratio = n.norm_bps && n.now_bps != null ? n.now_bps / n.norm_bps : null;
            const tone = !n.online ? 'bad' : n.drop_since ? 'warn' : 'ok';
            const row = (
              <>
                <span className={`dot dot--${tone === 'warn' ? 'warn' : tone}`} />
                <span className="speed-list__name">
                  {n.country_code && <span className="speed-list__cc">{n.country_code}</span>}
                  {n.name}
                </span>
                <span className="speed-list__bar" title={n.norm_bps ? 'Заполнение — текущая скорость относительно нормы' : 'Норма ещё набирается'}>
                  <span
                    className={`speed-list__fill speed-list__fill--${tone}`}
                    style={{ width: `${ratio == null ? 0 : Math.min(ratio, 1) * 100}%` }}
                  />
                </span>
                <span className="speed-list__nums">
                  {!n.online ? (
                    <b className="text-bad">offline</b>
                  ) : (
                    <>
                      <b>{n.now_bps == null ? '…' : formatSpeed(n.now_bps)}</b>
                      <span className="muted small">
                        {n.norm_bps == null ? 'норма набирается' : `норма ${formatSpeed(n.norm_bps)}`}
                      </span>
                    </>
                  )}
                </span>
              </>
            );
            return (
              <li key={n.uuid}>
                {n.domain_id ? (
                  <Link to={`/domains/${n.domain_id}`} className={`speed-list__row is-${tone}`} title="Открыть домен ноды">
                    {row}
                  </Link>
                ) : (
                  <div className={`speed-list__row is-${tone}`}>{row}</div>
                )}
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}

const IP_SOURCE = { cloudflare: 'A-запись Cloudflare', dns: 'DNS' };

function Verdict({ result }) {
  if (result.blocked === true) return <Badge tone="bad">В бане</Badge>;
  if (result.blocked === false) return <Badge tone="ok">Доступен</Badge>;
  return <Badge tone="warn">Не удалось проверить</Badge>;
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

const SOURCES = [
  { key: 'atlas', title: 'Red Atlas', hint: '3 точки в РФ + Европа + реестр' },
  { key: 'latencylab', title: 'Latency Lab', hint: 'проверка с провода' },
  { key: 'bschek', title: 'bschekbot', hint: 'мобильные операторы, платно' },
];
const SOURCES_KEY = 'cheker.iptool.sources';

function loadSources() {
  try {
    const v = JSON.parse(localStorage.getItem(SOURCES_KEY) || 'null');
    if (Array.isArray(v) && v.length) return v.filter((k) => SOURCES.some((s) => s.key === k));
  } catch {
    /* хранилище недоступно */
  }
  return ['atlas'];
}

function IpTool() {
  const [target, setTarget] = useState('');
  const [port, setPort] = useState('');
  const [sources, setSources] = useState(loadSources);
  const checks = { atlas: useCheck(), latencylab: useCheck(), bschek: useCheck() };

  const [units, setUnits] = useState(null);
  const [unitsError, setUnitsError] = useState('');
  const [selected, setSelected] = useState([]);
  const [opsOpen, setOpsOpen] = useState(false);

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
  const busy = SOURCES.some((src) => checks[src.key].busy);

  const toggleSource = (key) => {
    setSources((prev) => {
      const next = prev.includes(key) ? prev.filter((k) => k !== key) : [...prev, key];
      const ordered = SOURCES.map((src) => src.key).filter((k) => next.includes(k));
      try {
        localStorage.setItem(SOURCES_KEY, JSON.stringify(ordered));
      } catch {
        /* не сохранилось — не страшно */
      }
      return ordered;
    });
  };

  const runOne = (key) =>
    checks[key].run(() =>
      dashboardApi.check({
        target: value,
        checker: key,
        port: port || null,
        ...(key === 'bschek' ? { units: selected } : {}),
      }),
    );

  const canRun = (key) => value && !checks[key].busy && (key !== 'bschek' || selected.length > 0);

  const submit = (e) => {
    e.preventDefault();
    sources.filter(canRun).forEach(runOne);
  };

  // общий итог по уже пришедшим ответам
  const done = SOURCES.map((src) => ({ ...src, r: checks[src.key].result })).filter((x) => x.r);
  const first = done[0]?.r;
  const banned = done.filter((x) => x.r.blocked === true);
  const clean = done.filter((x) => x.r.blocked === false);
  const overall = !done.length
    ? null
    : banned.length
      ? { tone: 'bad', text: `В бане по данным: ${banned.map((x) => x.title).join(', ')}` }
      : clean.length
        ? { tone: 'ok', text: `Доступен${clean.length > 1 ? ` · подтвердили ${clean.length} источника` : ''}` }
        : { tone: 'warn', text: 'Не удалось проверить' };

  const shown = SOURCES.filter((src) => {
    const c = checks[src.key];
    return c.busy || c.result || c.error;
  });

  const details = (key, result) => {
    if (key === 'atlas') return <AtlasResult d={result.details} />;
    if (key === 'latencylab') return <LatencyDetails d={result.details || {}} />;
    return <BschekDetails d={result.details || {}} />;
  };

  return (
    <section className="card panel ipt">
      <div className="panel__head panel__head--stack">
        <h2 className="panel__title">Ручная проверка IP или домена</h2>
        <span className="muted small">Ничего не меняет — только показывает, доступен ли IP из России</span>
      </div>

      <form className="ipt-search" onSubmit={submit}>
        <label className="ipt-field">
          <IconSearch size={18} />
          <input
            className="ipt-field__input mono"
            placeholder="1.2.3.4 или de1.example.com"
            value={target}
            onChange={(e) => setTarget(e.target.value)}
            autoCapitalize="none"
            autoComplete="off"
            spellCheck={false}
            enterKeyHint="search"
          />
          {target && (
            <button type="button" className="ipt-field__clear" aria-label="Очистить" onClick={() => setTarget('')}>
              <IconX size={16} />
            </button>
          )}
        </label>
        <label className="ipt-port" title="Порт для проверки (пусто — из настроек)">
          <span>порт</span>
          <input
            className="mono"
            placeholder="443"
            value={port}
            onChange={(e) => setPort(e.target.value.replace(/\D/g, '').slice(0, 5))}
            inputMode="numeric"
          />
        </label>
        <button type="submit" className="btn btn--primary ipt-go" disabled={!value || !sources.some(canRun)}>
          {busy ? <Spinner size={16} /> : <IconSearch size={18} />}
          <span>{busy ? 'Проверяю…' : 'Проверить'}</span>
        </button>
      </form>

      <div className="ipt-sources" role="group" aria-label="Источники проверки">
        {SOURCES.map((src) => {
          const on = sources.includes(src.key);
          const c = checks[src.key];
          const state = c.busy ? 'busy' : c.result ? (c.result.blocked === true ? 'bad' : c.result.blocked === false ? 'ok' : 'warn') : c.error ? 'warn' : '';
          return (
            <button
              key={src.key}
              type="button"
              className={`ipt-source ${on ? 'is-on' : ''} ${state ? `is-${state}` : ''}`}
              aria-pressed={on}
              onClick={() => toggleSource(src.key)}
            >
              <span className="ipt-source__check" aria-hidden="true">
                <svg viewBox="0 0 16 16" width="11" height="11">
                  <path d="M3.5 8.5l3 3 6-7" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round" />
                </svg>
              </span>
              <span className="ipt-source__text">
                <b>{src.title}</b>
                <span>{src.hint}</span>
              </span>
              {c.busy && <Spinner size={14} />}
              {!c.busy && state && <span className={`ipt-source__dot ipt-source__dot--${state}`} />}
            </button>
          );
        })}
      </div>

      {sources.includes('bschek') && (
        <div className={`ipt-ops ${opsOpen ? 'is-open' : ''}`}>
          <button type="button" className="ipt-ops__toggle" onClick={() => setOpsOpen((v) => !v)}>
            <span>
              Операторы bschekbot · единиц: <b>{covered}</b>
              <span className="muted"> (каждая списывается отдельно)</span>
            </span>
            <IconChevronRight size={16} />
          </button>
          {opsOpen && (
            <div className="ipt-ops__body">
              {unitsError && <span className="field__hint text-warn">Операторы недоступны: {unitsError}</span>}
              {!units && !unitsError && <Spinner size={16} />}
              {units && <BschekOperatorPicker units={units} value={selected} onChange={setSelected} compact />}
            </div>
          )}
        </div>
      )}

      {overall && first && (
        <div className={`ipt-summary ipt-summary--${overall.tone}`}>
          <span className="ipt-summary__target">
            {first.domain && (
              <>
                <span className="mono">{first.domain}</span>
                <span className="muted"> → </span>
              </>
            )}
            <span className="mono ipt-summary__ip">{first.ip}</span>
            <span className="muted small">
              {' '}
              · порт {first.port}
              {first.domain && ` · IP из: ${IP_SOURCE[first.ip_source] || first.ip_source}`}
            </span>
          </span>
          <span className="ipt-summary__verdict">{overall.text}</span>
        </div>
      )}

      {shown.length > 0 && (
        <div className="ipt-results">
          {shown.map((src) => {
            const c = checks[src.key];
            return (
              <article key={src.key} className={`ipt-card ipt-card--${src.key}`}>
                <header className="ipt-card__head">
                  <b className="ipt-card__title">{src.title}</b>
                  {c.result && <Verdict result={c.result} />}
                  {c.busy && (
                    <span className="muted small ipt-card__busy">
                      <Spinner size={14} /> проверяю…
                    </span>
                  )}
                  <button
                    type="button"
                    className="icon-btn ipt-card__again"
                    title="Проверить ещё раз"
                    aria-label="Проверить ещё раз"
                    disabled={!canRun(src.key)}
                    onClick={() => runOne(src.key)}
                  >
                    <IconRefresh size={15} />
                  </button>
                </header>
                {c.error && <div className="alert alert--bad">{c.error}</div>}
                {c.result?.error && <p className="src-col__error">{c.result.error}</p>}
                {c.result && details(src.key, c.result)}
              </article>
            );
          })}
        </div>
      )}

      {busy && <p className="field__hint">Проверка может занять до пары минут — источники отвечают не сразу.</p>}
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
        subtitle="Состояние нод, доменов и IP. Обновляется само каждые 15 секунд"
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
          <HealthBanner data={data} running={running} />

          <div className="stats">
            <StatCard
              icon={IconServer}
              label="Ноды online"
              value={data.nodes.online}
              total={data.nodes.total}
              progress={data.nodes.total ? data.nodes.online / data.nodes.total : 0}
              tone={data.nodes.online === data.nodes.total ? 'ok' : 'bad'}
              hint={data.nodes.disabled ? `ещё отключено в панели: ${data.nodes.disabled}` : 'все активные ноды'}
              to="/nodes"
            />
            <StatCard
              icon={IconGlobe}
              label="Домены в порядке"
              value={data.domains.by_status.ok || 0}
              total={data.domains.total}
              progress={data.domains.total ? (data.domains.by_status.ok || 0) / data.domains.total : 0}
              tone={data.domains.problems.length ? 'warn' : 'ok'}
              hint={data.domains.problems.length ? `с проблемами: ${data.domains.problems.length}` : 'проблем нет'}
              to="/domains"
            />
            <StatCard
              icon={IconShield}
              label="IP в бане"
              value={data.ips.blocked}
              total={data.ips.total}
              tone={data.ips.blocked ? 'bad' : 'ok'}
              hint={`доступны: ${data.ips.clean}${data.ips.unknown ? ` · не проверены: ${data.ips.unknown}` : ''}`}
            />
            <StatCard
              icon={IconSwap}
              label="Смен IP за сутки"
              value={data.last_24h.switches_auto + data.last_24h.switches_manual}
              tone="accent"
              hint={`авто ${data.last_24h.switches_auto} · вручную ${data.last_24h.switches_manual} · банов ${data.last_24h.blocked}`}
              to="/events"
            />
          </div>

          <div className="dash-grid">
            <section className="card panel">
              <h2 className="panel__title">Требует внимания</h2>
              {data.nodes.offline.length === 0 && data.domains.problems.length === 0 ? (
                <div className="all-good">
                  <IconCheck size={22} />
                  <div>
                    <b>Всё в порядке</b>
                    <span className="muted small">Нет упавших нод и доменов с проблемами</span>
                  </div>
                </div>
              ) : (
                <ul className="attention">
                  {data.nodes.offline.map((n) => (
                    <li key={n.uuid}>
                      <Link to="/nodes" className="attention__item attention__item--bad">
                        <span className="attention__icon">
                          <IconServer size={18} />
                        </span>
                        <div className="attention__body">
                          <span className="attention__name">{n.name}</span>
                          <span className="attention__meta">
                            Нода offline{n.since ? ` уже ${formatDuration(n.since)}` : ''}
                            {n.message ? ` · ${n.message}` : ''}
                          </span>
                        </div>
                        <IconChevronRight size={16} className="attention__chev" />
                      </Link>
                    </li>
                  ))}
                  {data.domains.problems.map((d) => {
                    const tone = DOMAIN_STATUS[d.status]?.tone || 'muted';
                    return (
                      <li key={d.id}>
                        <Link to={`/domains/${d.id}`} className={`attention__item attention__item--${tone}`}>
                          <span className="attention__icon">
                            <IconGlobe size={18} />
                          </span>
                          <div className="attention__body">
                            <span className="attention__name mono">{d.name}</span>
                            <span className="attention__meta">
                              {DOMAIN_STATUS[d.status]?.label || d.status} · <span className="mono">{d.current_ip || 'нет IP'}</span>
                              {d.message ? ` · ${d.message}` : ''}
                            </span>
                          </div>
                          <IconChevronRight size={16} className="attention__chev" />
                        </Link>
                      </li>
                    );
                  })}
                </ul>
              )}
            </section>

            <SpeedPanel speeds={data.speeds} />
          </div>

          <div className="dash-grid">
            <section className="card panel">
              <div className="panel__head">
                <h2 className="panel__title">Проверки IP после падения скорости</h2>
              </div>
              {data.investigations.length === 0 ? (
                <EmptyState
                  title="Проверок пока не было"
                  text="Когда у ноды упадёт скорость, здесь появится проверка IP её домена"
                />
              ) : (
                <InvestigationList items={data.investigations.slice(0, 5)} onChanged={reload} />
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
                  {data.recent_events.slice(0, 8).map((e) => (
                    <EventItem key={e.id} event={e} compact />
                  ))}
                </ul>
              )}
            </section>
          </div>

          <IpTool />
        </>
      )}
      {confirmAll && (
        <ConfirmModal
          title="Проверить все домены"
          text="Будет проверен текущий IP каждого включённого домена и IP — с нодой и без. Cloudflare используется только если IP в бане и его нужно сменить. При бане IP сменится сразу, без трёх проверок."
          confirmText="Проверить"
          onConfirm={checkNow}
          onClose={() => setConfirmAll(false)}
        />
      )}
    </div>
  );
}
