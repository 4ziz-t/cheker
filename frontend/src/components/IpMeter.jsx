const SEGMENTS = 5;

function IconTriangleAlert({ size = 16 }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <path
        d="M10.3 3.9 1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0z"
        fill="currentColor"
        fillOpacity="0.16"
        stroke="currentColor"
        strokeWidth="1.8"
        strokeLinejoin="round"
      />
      <path d="M12 9v4.5M12 17.2h.01" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" />
    </svg>
  );
}

function IconCircleAlert({ size = 16 }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <circle cx="12" cy="12" r="9.2" fill="currentColor" fillOpacity="0.16" stroke="currentColor" strokeWidth="1.8" />
      <path d="M12 7.5v5.5M12 16.6h.01" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" />
    </svg>
  );
}

/**
 * Индикатор IP домена: 5 делений, заполнено по доле IP «в порядке», рядом «в порядке/всего».
 * Красный треугольник — есть IP в бане, жёлтый круг — есть непроверенные IP.
 */
export default function IpMeter({ ok = 0, total = 0, blocked = 0, unknown = 0 }) {
  if (!total) return <span className="muted">нет IP</span>;
  const ratio = ok / total;
  const filled = ok ? Math.max(1, Math.round(ratio * SEGMENTS)) : 0;
  const tone = ratio >= 0.66 ? 'ok' : ratio >= 0.25 ? 'warn' : 'bad';
  const title = [
    `В порядке: ${ok} из ${total}`,
    blocked ? `в бане: ${blocked}` : '',
    unknown ? `не проверены: ${unknown}` : '',
  ]
    .filter(Boolean)
    .join(' · ');

  return (
    <span className="ip-meter" title={title} role="img" aria-label={title}>
      <span className="ip-meter__bar" aria-hidden="true">
        {Array.from({ length: SEGMENTS }, (_, i) => (
          <span key={i} className={`ip-meter__seg ${i < filled ? `ip-meter__seg--${tone}` : ''}`} />
        ))}
      </span>
      <span className="ip-meter__count">
        {ok}/{total}
      </span>
      {blocked > 0 && (
        <span className="ip-meter__flag ip-meter__flag--bad" title={`В бане: ${blocked}`}>
          <IconTriangleAlert />
        </span>
      )}
      {unknown > 0 && (
        <span className="ip-meter__flag ip-meter__flag--warn" title={`Не проверены: ${unknown}`}>
          <IconCircleAlert />
        </span>
      )}
    </span>
  );
}
