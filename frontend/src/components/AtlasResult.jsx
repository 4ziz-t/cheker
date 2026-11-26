import { formatRelative } from '../utils/format.js';

const STATUS = {
  open: { tone: 'ok', label: 'Открывается из России' },
  partial: { tone: 'warn', label: 'Открывается не из всех сетей' },
  mixed: { tone: 'warn', label: 'Закрыты отдельные адреса' },
  blocked: { tone: 'bad', label: 'Заблокирован в России' },
  down: { tone: 'muted', label: 'Не работает нигде' },
};

// пометка «в реестре» показывается отдельно и статус не перекрывает: решает доступность из России
function statusOf(d) {
  return STATUS[d.status] || { tone: 'muted', label: d.status_text || 'Нет данных' };
}

function Point({ p, region }) {
  const tone = p.ok === true ? 'ok' : p.ok === false ? 'bad' : 'muted';
  return (
    <li className={`atlas-point atlas-point--${tone}`}>
      <span className="atlas-point__region">{region}</span>
      <span className="atlas-point__place">
        <b>{p.city || '—'}</b>
        <span className="muted small">
          {p.net}
          {p.asn ? ` · AS${p.asn}` : ''}
        </span>
      </span>
      <span className="atlas-point__rtt">{p.ok && p.rtt != null ? `${p.rtt} мс` : ''}</span>
      <span className={`atlas-point__state atlas-point__state--${tone}`}>
        {p.ok === true ? 'открывается' : p.ok === false ? 'закрыт' : 'нет ответа'}
      </span>
    </li>
  );
}

/** Результат Red Atlas. compact — одной строкой (список IP домена). */
export default function AtlasResult({ d, compact = false }) {
  if (!d || (!d.status && !d.ru?.length)) return null;
  const st = statusOf(d);
  const ru = d.ru || [];
  const ctrl = d.ctrl || [];
  const europeOk = ctrl.length ? ctrl.some((p) => p.ok) : d.ctrl_ok > 0;

  if (compact) {
    return (
      <span className="atlas-inline">
        <span className={`atlas-pill atlas-pill--${st.tone}`}>{st.label}</span>
        <span className="atlas-inline__dots" title="Точки в России">
          {ru.map((p, i) => (
            <span
              key={i}
              className={`atlas-dot atlas-dot--${p.ok ? 'ok' : p.ok === false ? 'bad' : 'muted'}`}
              title={`${p.city}, ${p.net}: ${p.ok ? 'открывается' : 'закрыт'}`}
            />
          ))}
          <span className="muted small">
            РФ {d.ru_ok}/{d.ru_total}
          </span>
        </span>
        {ctrl.length > 0 && (
          <span className={`muted small ${europeOk ? '' : 'text-bad'}`}>Европа {europeOk ? '✓' : '✗'}</span>
        )}
        {d.registry_blocked && (
          <span className="atlas-pill atlas-pill--warn" title="Адрес есть в реестре, но решает доступность из России">
            в реестре
          </span>
        )}
      </span>
    );
  }

  return (
    <div className={`atlas atlas--${st.tone}`}>
      <div className="atlas__head">
        <span className={`atlas-pill atlas-pill--${st.tone} atlas-pill--lg`}>{st.label}</span>
        {d.reason_text && <span className="atlas__reason">{d.reason_text}</span>}
      </div>

      <div className="atlas__stats">
        <div className="atlas-stat">
          <span className="atlas-stat__label">Из России</span>
          <span className="atlas-stat__value">
            {d.ru_ok}
            <span className="muted"> из {d.ru_total}</span>
          </span>
          <span className="atlas-stat__bar">
            {ru.map((p, i) => (
              <span key={i} className={`atlas-stat__seg atlas-stat__seg--${p.ok ? 'ok' : 'bad'}`} />
            ))}
          </span>
        </div>
        <div className="atlas-stat">
          <span className="atlas-stat__label">Контроль из Европы</span>
          <span className={`atlas-stat__value ${europeOk ? 'text-ok' : 'text-bad'}`}>
            {ctrl.length || d.ctrl_ok != null ? (europeOk ? 'открывается' : 'закрыт') : '—'}
          </span>
          <span className="muted small">значит, сам сервер {europeOk ? 'работает' : 'может не работать'}</span>
        </div>
        <div className="atlas-stat">
          <span className="atlas-stat__label">Реестр блокировок</span>
          <span className={`atlas-stat__value ${d.registry_blocked ? 'text-warn' : 'text-ok'}`}>
            {d.registry_blocked == null ? '—' : d.registry_blocked ? 'есть в реестре' : 'нет'}
          </span>
          {d.registry_blocked && <span className="muted small">это пометка: решает доступность из России</span>}
          {d.whitelist != null && <span className="muted small">белый список: {d.whitelist ? 'да' : 'нет'}</span>}
        </div>
      </div>

      {(ru.length > 0 || ctrl.length > 0) && (
        <ul className="atlas__points">
          {ru.map((p, i) => (
            <Point key={`ru-${i}`} p={p} region="RU" />
          ))}
          {ctrl.map((p, i) => (
            <Point key={`eu-${i}`} p={p} region="EU" />
          ))}
        </ul>
      )}

      <div className="atlas__foot muted small">
        {d.proto && <span>{String(d.proto).toUpperCase()}</span>}
        {d.port && <span>порт {d.port}</span>}
        {d.checked_at && <span>проверено {formatRelative(new Date(d.checked_at * 1000).toISOString())}</span>}
        {d.cached && <span>из кэша Red Atlas (до 10 мин)</span>}
      </div>
    </div>
  );
}
