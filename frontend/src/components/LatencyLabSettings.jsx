import { useEffect, useState } from 'react';
import { settingsApi } from '../api/index.js';
import Spinner from './Spinner.jsx';
import Toggle from './Toggle.jsx';

export default function LatencyLabSettings({ form, set }) {
  const [operators, setOperators] = useState(null);
  const [error, setError] = useState('');

  useEffect(() => {
    settingsApi
      .latencylabOperators()
      .then(setOperators)
      .catch((e) => setError(e.message));
  }, []);

  const selected = form.latencylab_operators || [];
  const toggle = (id) =>
    set('latencylab_operators', selected.includes(id) ? selected.filter((x) => x !== id) : [...selected, id]);

  return (
    <div className="form">
      <div className="field">
        <span className="field__label">
          Операторы <span className="muted">· {selected.length ? `выбрано ${selected.length}` : 'все онлайн'}</span>
        </span>
        {error && <span className="field__hint text-warn">Список операторов недоступен: {error}</span>}
        {!operators && !error && <Spinner size={16} />}
        {operators && (
          <div className="city-chips">
            {operators.map((o) => (
              <button
                key={o.id}
                type="button"
                className={`chip chip--sm ${selected.includes(o.id) ? 'is-active' : ''}`}
                onClick={() => toggle(o.id)}
                title={o.wl ? 'У оператора режим белых списков' : ''}
              >
                <span className={`dot ${o.online ? 'dot--ok' : 'dot--off'}`} />
                {o.label}
                {o.wl && <span className="chip__count">wl</span>}
              </button>
            ))}
          </div>
        )}
        <span className="field__hint">Ничего не выбрано — проверка через всех операторов, кто сейчас онлайн.</span>
      </div>

      <label className="field">
        <span className="field__label">Считать IP заблокированным, если недоступен</span>
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
      </label>

      <Toggle
        checked={form.latencylab_skip_whitelist}
        onChange={(v) => set('latencylab_skip_whitelist', v)}
        label="Не учитывать операторов в режиме белых списков (wl)"
        hint="В режиме белых списков недоступно почти всё — это даст ложные баны"
      />
    </div>
  );
}
