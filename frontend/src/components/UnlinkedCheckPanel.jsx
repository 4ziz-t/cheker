import { useEffect, useState } from 'react';
import { dashboardApi, settingsApi } from '../api/index.js';
import { formatRelative } from '../utils/format.js';
import { useToast } from './Toast.jsx';
import Toggle from './Toggle.jsx';

/**
 * Автопроверка доменов/IP, к которым не привязана ни одна нода Remnawave.
 * Включается переключателем, интервал по умолчанию — 1 час.
 */
export default function UnlinkedCheckPanel({ unlinkedCount }) {
  const toast = useToast();
  const [enabled, setEnabled] = useState(false);
  const [interval, setIntervalValue] = useState(60);
  const [savedInterval, setSavedInterval] = useState(60);
  const [nextAt, setNextAt] = useState(null);
  const [busy, setBusy] = useState(false);
  const [loaded, setLoaded] = useState(false);

  const loadStatus = () =>
    dashboardApi
      .status()
      .then((st) => setNextAt(st.unlinked_next_check_at))
      .catch(() => {});

  useEffect(() => {
    settingsApi
      .get()
      .then((s) => {
        setEnabled(!!s.values.unlinked_check_enabled);
        setIntervalValue(s.values.unlinked_check_interval_minutes);
        setSavedInterval(s.values.unlinked_check_interval_minutes);
        setLoaded(true);
      })
      .catch(() => {});
    loadStatus();
  }, []);

  const save = async (patch, okText) => {
    setBusy(true);
    try {
      const res = await settingsApi.update(patch);
      setEnabled(!!res.values.unlinked_check_enabled);
      setIntervalValue(res.values.unlinked_check_interval_minutes);
      setSavedInterval(res.values.unlinked_check_interval_minutes);
      toast.success(okText);
      setTimeout(loadStatus, 1500);
    } catch (e) {
      toast.error(e.message);
    } finally {
      setBusy(false);
    }
  };

  if (!loaded) return null;

  const intervalDirty = Number(interval) !== Number(savedInterval);

  return (
    <section className="card panel unlinked">
      <div className="unlinked__row">
        <Toggle
          checked={enabled}
          disabled={busy}
          onChange={(v) =>
            save({ unlinked_check_enabled: v }, v ? 'Автопроверка включена' : 'Автопроверка выключена')
          }
          label="Автопроверка доменов и IP без ноды"
          hint={`Без привязанной ноды Remnawave: ${unlinkedCount}. Проверяется текущий IP (1 запрос к источникам на домен), при бане — сразу смена A-записи`}
        />
      </div>
      {enabled && (
        <div className="unlinked__row unlinked__settings">
          <label className="field">
            <span className="field__label">Интервал проверки</span>
            <div className="input-suffix">
              <input
                className="input"
                type="number"
                min={5}
                max={10080}
                value={interval}
                onChange={(e) => setIntervalValue(e.target.value)}
              />
              <span>мин</span>
              {intervalDirty && (
                <button
                  type="button"
                  className="btn btn--sm btn--primary"
                  disabled={busy}
                  onClick={() =>
                    save({ unlinked_check_interval_minutes: Number(interval) }, 'Интервал сохранён')
                  }
                >
                  Сохранить
                </button>
              )}
            </div>
          </label>
          <span className="muted small">
            {nextAt ? `Следующая проверка ${formatRelative(nextAt)}` : 'Расписание обновляется…'}
          </span>
        </div>
      )}
    </section>
  );
}
