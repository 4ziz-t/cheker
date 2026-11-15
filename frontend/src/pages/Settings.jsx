import { useEffect, useMemo, useState } from 'react';
import { dashboardApi, settingsApi } from '../api/index.js';
import Badge from '../components/Badge.jsx';
import { IconLogout, IconSend } from '../components/Icons.jsx';
import PageHeader, { ErrorBox } from '../components/PageHeader.jsx';
import Spinner from '../components/Spinner.jsx';
import { useToast } from '../components/Toast.jsx';
import Toggle from '../components/Toggle.jsx';
import '../styles/settings.css';

const INTEGRATIONS = [
  { key: 'remnawave', label: 'Remnawave', env: 'REMNAWAVE_URL, REMNAWAVE_TOKEN' },
  { key: 'cloudflare', label: 'Cloudflare', env: 'CLOUDFLARE_API_TOKEN' },
  { key: 'telegram', label: 'Telegram', env: 'TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID' },
];

function NumberField({ label, hint, value, onChange, min, max, suffix }) {
  return (
    <label className="field">
      <span className="field__label">{label}</span>
      <div className="input-suffix">
        <input
          className="input"
          type="number"
          min={min}
          max={max}
          value={value ?? ''}
          onChange={(e) => onChange(e.target.value === '' ? '' : Number(e.target.value))}
        />
        {suffix && <span>{suffix}</span>}
      </div>
      {hint && <span className="field__hint">{hint}</span>}
    </label>
  );
}

export default function Settings({ onLogout }) {
  const toast = useToast();
  const [meta, setMeta] = useState(null);
  const [saved, setSaved] = useState(null);
  const [form, setForm] = useState(null);
  const [status, setStatus] = useState(null);
  const [error, setError] = useState(null);
  const [saving, setSaving] = useState(false);
  const [testing, setTesting] = useState('');

  const load = async () => {
    try {
      const [s, st] = await Promise.all([settingsApi.get(), dashboardApi.status()]);
      setMeta({ eventTypes: s.event_types, checkers: s.checkers });
      setSaved(s.values);
      setForm(s.values);
      setStatus(st);
      setError(null);
    } catch (e) {
      setError(e);
    }
  };

  useEffect(() => {
    load();
  }, []);

  const dirty = useMemo(() => JSON.stringify(form) !== JSON.stringify(saved), [form, saved]);
  const set = (key, value) => setForm((f) => ({ ...f, [key]: value }));

  const save = async () => {
    setSaving(true);
    try {
      const res = await settingsApi.update(form);
      setSaved(res.values);
      setForm(res.values);
      toast.success('Настройки сохранены');
    } catch (e) {
      toast.error(e.message);
    } finally {
      setSaving(false);
    }
  };

  const test = async (kind) => {
    setTesting(kind);
    try {
      if (kind === 'telegram') await settingsApi.testTelegram();
      else await settingsApi.testSummary();
      toast.success('Отправлено в Telegram');
    } catch (e) {
      toast.error(e.message);
    } finally {
      setTesting('');
    }
  };

  if (!form) {
    return (
      <div className="page">
        <PageHeader title="Настройки" />
        {error ? <ErrorBox error={error} onRetry={load} /> : <div className="page-loading"><Spinner size={28} /></div>}
      </div>
    );
  }

  const toggleChecker = (name, on) => {
    const list = new Set(form.enabled_checkers);
    if (on) list.add(name);
    else list.delete(name);
    set('enabled_checkers', [...list]);
  };

  return (
    <div className="page page--settings">
      <PageHeader
        title="Настройки"
        actions={
          <button type="button" className="btn btn--ghost btn--danger-text" onClick={onLogout}>
            <IconLogout size={18} />
            <span>Выйти</span>
          </button>
        }
      />

      <div className="settings-grid">
        <section className="card panel">
          <h2 className="panel__title">Проверка доменов</h2>
          <div className="form">
            <NumberField
              label="Интервал проверки"
              suffix="мин"
              min={1}
              max={1440}
              value={form.check_interval_minutes}
              onChange={(v) => set('check_interval_minutes', v)}
              hint="Как часто проверять все IP всех доменов"
            />
            <NumberField
              label="Пауза между запросами к чекерам"
              suffix="мс"
              min={0}
              max={60000}
              value={form.checker_delay_ms}
              onChange={(v) => set('checker_delay_ms', v)}
              hint="Защита от лимитов (429) на стороне сервиса проверки"
            />
            <Toggle
              checked={form.auto_switch_enabled}
              onChange={(v) => set('auto_switch_enabled', v)}
              label="Автосмена IP (глобально)"
              hint="Выключите, чтобы временно остановить все автоматические смены"
            />
          </div>
        </section>

        <section className="card panel">
          <h2 className="panel__title">Ноды Remnawave</h2>
          <div className="form">
            <NumberField
              label="Интервал опроса нод"
              suffix="сек"
              min={10}
              max={3600}
              value={form.node_poll_interval_seconds}
              onChange={(v) => set('node_poll_interval_seconds', v)}
              hint="Как быстро вы узнаете, что нода упала"
            />
          </div>
        </section>

        <section className="card panel">
          <h2 className="panel__title">Источники проверки IP</h2>
          <div className="form">
            {meta.checkers.map((c) => (
              <Toggle
                key={c.name}
                checked={form.enabled_checkers.includes(c.name)}
                onChange={(v) => toggleChecker(c.name, v)}
                label={c.title}
                hint={c.description}
              />
            ))}
            <span className="field__hint">IP считается заблокированным, если его видит в бане хотя бы один источник.</span>
          </div>
        </section>

        <section className="card panel">
          <h2 className="panel__title">Ежедневная сводка</h2>
          <div className="form">
            <Toggle
              checked={form.daily_summary_enabled}
              onChange={(v) => set('daily_summary_enabled', v)}
              label="Отправлять сводку"
            />
            <label className="field">
              <span className="field__label">Время отправки ({status?.timezone})</span>
              <input
                className="input"
                type="time"
                value={form.daily_summary_time}
                onChange={(e) => set('daily_summary_time', e.target.value)}
              />
            </label>
            <button
              type="button"
              className="btn btn--ghost"
              disabled={!!testing}
              onClick={() => test('summary')}
            >
              {testing === 'summary' ? <Spinner size={16} /> : <IconSend size={16} />}
              <span>Отправить сводку сейчас</span>
            </button>
          </div>
        </section>

        <section className="card panel panel--wide">
          <div className="panel__head">
            <h2 className="panel__title">Уведомления в Telegram</h2>
            <button
              type="button"
              className="btn btn--sm btn--ghost"
              disabled={!!testing}
              onClick={() => test('telegram')}
            >
              {testing === 'telegram' ? <Spinner size={16} /> : <IconSend size={16} />}
              <span>Тест</span>
            </button>
          </div>
          <div className="notify-grid">
            {Object.entries(meta.eventTypes).map(([key, label]) => (
              <Toggle
                key={key}
                checked={form.notify[key]}
                onChange={(v) => set('notify', { ...form.notify, [key]: v })}
                label={label}
              />
            ))}
          </div>
        </section>

        <section className="card panel">
          <h2 className="panel__title">Хранение</h2>
          <div className="form">
            <NumberField
              label="Хранить события"
              suffix="дней"
              min={1}
              max={3650}
              value={form.events_retention_days}
              onChange={(v) => set('events_retention_days', v)}
            />
          </div>
        </section>

        <section className="card panel">
          <h2 className="panel__title">Интеграции</h2>
          <ul className="integrations">
            {INTEGRATIONS.map((i) => (
              <li key={i.key}>
                <div>
                  <span className="integrations__name">{i.label}</span>
                  <span className="field__hint mono">{i.env}</span>
                </div>
                {status?.integrations?.[i.key] ? (
                  <Badge tone="ok">Настроено</Badge>
                ) : (
                  <Badge tone="warn">Нет в .env</Badge>
                )}
              </li>
            ))}
          </ul>
          <p className="field__hint">Токены и пароль задаются только в .env на сервере и не отображаются в панели.</p>
        </section>
      </div>

      <div className={`savebar ${dirty ? 'is-visible' : ''}`}>
        <span>Есть несохранённые изменения</span>
        <div className="savebar__actions">
          <button type="button" className="btn btn--ghost" onClick={() => setForm(saved)} disabled={saving}>
            Сбросить
          </button>
          <button type="button" className="btn btn--primary" onClick={save} disabled={saving}>
            {saving ? 'Сохраняю…' : 'Сохранить'}
          </button>
        </div>
      </div>
    </div>
  );
}
