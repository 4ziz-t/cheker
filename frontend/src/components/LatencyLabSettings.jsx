import Toggle from './Toggle.jsx';

const MODES = [
  { value: 'auto', label: 'Авто: /tspu, а если ключу он не разрешён — TCP через операторов' },
  { value: 'tspu', label: 'Только /tspu (проверка бана ТСПУ с провода)' },
  { value: 'multiscan', label: 'Только TCP через мобильных операторов (/multiscan)' },
];

export default function LatencyLabSettings({ form, set }) {
  const mode = form.latencylab_mode || 'auto';
  return (
    <div className="form">
      <label className="field">
        <span className="field__label">Режим проверки</span>
        <select className="input select select--wide" value={mode} onChange={(e) => set('latencylab_mode', e.target.value)}>
          {MODES.map((m) => (
            <option key={m.value} value={m.value}>
              {m.label}
            </option>
          ))}
        </select>
        <span className="field__hint">
          Метод /tspu доступен не для всех API-ключей. В режиме «Авто» при ответе 403 Cheker переходит на TCP через
          операторов и раз в 6 часов пробует /tspu снова.
        </span>
      </label>

      {mode !== 'multiscan' && (
        <Toggle
          checked={form.latencylab_throttle_is_ban}
          onChange={(v) => set('latencylab_throttle_is_ban', v)}
          label="Считать замедление ТСПУ баном (/tspu)"
          hint="Если Latency Lab видит throttling (обрыв или торможение после 16 КБ), переключать IP"
        />
      )}

      {mode !== 'tspu' && (
        <label className="field">
          <span className="field__label">Бан, если порт недоступен (TCP через операторов)</span>
          <div className="input-suffix">
            <input
              className="input"
              type="number"
              min={1}
              max={100}
              value={form.latencylab_fail_percent ?? ''}
              onChange={(e) => set('latencylab_fail_percent', e.target.value === '' ? '' : Number(e.target.value))}
            />
            <span>% операторов и более</span>
          </div>
          <span className="field__hint">Операторы в режиме белых списков не учитываются.</span>
        </label>
      )}
    </div>
  );
}
