import { useEffect, useState } from 'react';
import { settingsApi } from '../api/index.js';
import BschekOperatorPicker, { countCovered } from './BschekOperatorPicker.jsx';
import Spinner from './Spinner.jsx';

export default function BschekSettings({ form, set }) {
  const [units, setUnits] = useState(null);
  const [error, setError] = useState('');
  const [text, setText] = useState('');
  const selected = form.bschek_units || [];

  useEffect(() => {
    settingsApi
      .bschekUnits()
      .then(setUnits)
      .catch((e) => setError(e.message));
  }, []);

  useEffect(() => {
    setText(selected.join(', '));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [form.bschek_units]);

  const applyText = () =>
    set(
      'bschek_units',
      [
        ...new Set(
          text
            .split(/[,\s]+/)
            .map((s) => s.trim())
            .filter(Boolean),
        ),
      ],
    );

  return (
    <div className="form">
      <span className="field__hint">Операторы для автоматических проверок (после падения скорости ноды).</span>
      {error && <span className="field__hint text-warn">Список операторов недоступен: {error}</span>}
      {!units && !error && <Spinner size={16} />}
      {units && (
        <BschekOperatorPicker units={units} value={selected} onChange={(v) => set('bschek_units', v)} />
      )}

      <p className="field__hint">
        Цифра у оператора — сколько его округов сейчас доступно; каждый округ — отдельное списание. Под текущий выбор
        подходит единиц: <b>{countCovered(units, selected)}</b>
        {!selected.length && ' — ничего не выбрано, проверка не пойдёт'}.
      </p>

      <details className="bs-advanced">
        <summary>Точная настройка (ключи оператор|округ|БС)</summary>
        <label className="field">
          <input
            className="input mono"
            value={text}
            onChange={(e) => setText(e.target.value)}
            onBlur={applyText}
            placeholder="mts|*|off, beeline|цфо|on"
            spellCheck={false}
          />
          <span className="field__hint">
            Через запятую. Например «mts|цфо|off» — только МТС в ЦФО без БС, «*|*|on» — все операторы с БС.
          </span>
        </label>
      </details>

      <label className="field">
        <span className="field__label">Бан, если порт недоступен у</span>
        <div className="input-suffix">
          <input
            className="input"
            type="number"
            min={1}
            max={100}
            value={form.bschek_fail_percent ?? ''}
            onChange={(e) => set('bschek_fail_percent', e.target.value === '' ? '' : Number(e.target.value))}
          />
          <span>% единиц и более</span>
        </div>
      </label>
    </div>
  );
}
