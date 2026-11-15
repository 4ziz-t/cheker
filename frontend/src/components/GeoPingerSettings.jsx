import { useEffect, useState } from 'react';
import { settingsApi } from '../api/index.js';
import Spinner from './Spinner.jsx';

function CityPicker({ label, hint, cities, value, onChange, filter }) {
  const list = cities.filter(filter);
  const toggle = (city) =>
    onChange(value.includes(city) ? value.filter((c) => c !== city) : [...value, city]);
  return (
    <div className="field">
      <span className="field__label">
        {label} <span className="muted">· выбрано {value.length}</span>
      </span>
      <div className="city-chips">
        {list.map((c) => (
          <button
            key={c.city}
            type="button"
            className={`chip chip--sm ${value.includes(c.city) ? 'is-active' : ''}`}
            title={c.providers.length ? c.providers.join(', ') : ''}
            onClick={() => toggle(c.city)}
          >
            {c.city}
            {c.count > 1 && <span className="chip__count">{c.count}</span>}
          </button>
        ))}
        {/* выбранные города, которых сейчас нет среди активных сенсоров */}
        {value
          .filter((v) => !list.some((c) => c.city === v))
          .map((v) => (
            <button key={v} type="button" className="chip chip--sm is-active is-stale" onClick={() => toggle(v)}>
              {v} · нет сенсоров
            </button>
          ))}
      </div>
      {hint && <span className="field__hint">{hint}</span>}
    </div>
  );
}

export default function GeoPingerSettings({ form, set }) {
  const [cities, setCities] = useState(null);
  const [error, setError] = useState('');

  useEffect(() => {
    settingsApi
      .geopingerSensors()
      .then(setCities)
      .catch((e) => setError(e.message));
  }, []);

  const pointsPerCheck = form.geopinger_places.length + form.geopinger_control_places.length;

  return (
    <div className="form">
      <label className="field">
        <span className="field__label">Считать IP заблокированным, если не подключились</span>
        <div className="input-suffix">
          <input
            className="input"
            type="number"
            min={1}
            max={100}
            value={form.geopinger_fail_percent ?? ''}
            onChange={(e) => set('geopinger_fail_percent', e.target.value === '' ? '' : Number(e.target.value))}
          />
          <span>% узлов РФ и более</span>
        </div>
      </label>

      {error && (
        <div className="alert alert--warn">
          <span>Список сенсоров недоступен: {error}</span>
        </div>
      )}
      {!cities && !error && <Spinner size={18} />}
      {cities && (
        <>
          <CityPicker
            label="Города в РФ для проверки"
            cities={cities}
            value={form.geopinger_places}
            onChange={(v) => set('geopinger_places', v)}
            filter={(c) => c.ccode === 'ru'}
          />
          <CityPicker
            label="Контрольные города вне РФ (необязательно)"
            hint="Если IP не отвечает и оттуда — значит сервер лежит, а не забанен. Тогда автосмены не будет."
            cities={cities}
            value={form.geopinger_control_places}
            onChange={(v) => set('geopinger_control_places', v)}
            filter={(c) => c.ccode !== 'ru'}
          />
        </>
      )}
      <span className="field__hint">
        Точек на одну проверку IP: {pointsPerCheck} ≈ {(pointsPerCheck * 0.02).toFixed(2)} ₽.
      </span>
    </div>
  );
}
