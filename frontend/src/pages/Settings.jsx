import { useEffect, useMemo, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { dashboardApi, settingsApi } from '../api/index.js';
import { IconLogout, IconSend } from '../components/Icons.jsx';
import IntegrationsPanel from '../components/IntegrationsPanel.jsx';
import AtlasSettings from '../components/AtlasSettings.jsx';
import LatencyLabSettings from '../components/LatencyLabSettings.jsx';
import BschekSettings from '../components/BschekSettings.jsx';
import PageHeader, { ErrorBox } from '../components/PageHeader.jsx';
import Spinner from '../components/Spinner.jsx';
import { useToast } from '../components/Toast.jsx';
import Toggle from '../components/Toggle.jsx';
import '../styles/settings.css';

const TABS = [
  { key: 'integrations', label: 'Интеграции' },
  { key: 'checks', label: 'Проверка' },
  { key: 'sources', label: 'Источники' },
  { key: 'notify', label: 'Уведомления' },
  { key: 'system', label: 'Система' },
];

// какие источники имеют свой блок настроек
const SOURCE_SETTINGS = {
  atlas: AtlasSettings,
  latencylab: LatencyLabSettings,
  bschek: BschekSettings,
};

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

function Panel({ title, children, actions, wide }) {
  return (
    <section className={`card panel ${wide ? 'panel--wide' : ''}`}>
      <div className="panel__head">
        <h2 className="panel__title">{title}</h2>
        {actions}
      </div>
      {children}
    </section>
  );
}

export default function Settings({ onLogout }) {
  const toast = useToast();
  const [params, setParams] = useSearchParams();
  const tab = TABS.some((t) => t.key === params.get('tab')) ? params.get('tab') : 'integrations';

  const [meta, setMeta] = useState(null);
  const [saved, setSaved] = useState(null);
  const [form, setForm] = useState(null);
  const [status, setStatus] = useState(null);
  const [error, setError] = useState(null);
  const [saving, setSaving] = useState(false);
  const [testing, setTesting] = useState('');
  const [checkerStatus, setCheckerStatus] = useState({});

  const loadCheckerStatus = () => settingsApi.checkersStatus().then(setCheckerStatus).catch(() => {});

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
    loadCheckerStatus();
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

  const header = (
    <PageHeader
      title="Настройки"
      actions={
        <button type="button" className="btn btn--ghost btn--danger-text" onClick={onLogout}>
          <IconLogout size={18} />
          <span>Выйти</span>
        </button>
      }
    />
  );

  if (!form) {
    return (
      <div className="page">
        {header}
        {error ? (
          <ErrorBox error={error} onRetry={load} />
        ) : (
          <div className="page-loading">
            <Spinner size={28} />
          </div>
        )}
      </div>
    );
  }

  const toggleChecker = (name, on) => {
    const list = new Set(form.enabled_checkers);
    if (on) list.add(name);
    else list.delete(name);
    // сохраняем порядок из реестра
    set(
      'enabled_checkers',
      meta.checkers.map((c) => c.name).filter((n) => list.has(n)),
    );
  };

  return (
    <div className="page page--settings">
      {header}

      <nav className="tabs" role="tablist">
        {TABS.map((t) => (
          <button
            key={t.key}
            type="button"
            role="tab"
            aria-selected={tab === t.key}
            className={`tabs__item ${tab === t.key ? 'is-active' : ''}`}
            onClick={() => setParams({ tab: t.key }, { replace: true })}
          >
            {t.label}
          </button>
        ))}
      </nav>

      {tab === 'integrations' && (
        <>
          <p className="field__hint">
            Токены и адреса сервисов. Значения из панели важнее, чем из .env. Секреты не показываются целиком: чтобы
            заменить, введите новое значение.
          </p>
          <IntegrationsPanel onChanged={loadCheckerStatus} />
        </>
      )}

      {tab === 'checks' && (
        <div className="settings-grid">
          <Panel title="Падение скорости ноды">
            <div className="form">
              <p className="field__hint">
                IP доменов проверяются только тогда, когда у привязанной ноды Remnawave упала скорость.
              </p>
              <NumberField
                label="Скорость упала на"
                suffix="% от нормы и больше"
                min={10}
                max={100}
                value={form.speed_drop_percent}
                onChange={(v) => set('speed_drop_percent', v)}
              />
              <NumberField
                label="Норма — средняя скорость за"
                suffix="ч"
                min={1}
                max={48}
                value={form.speed_baseline_hours}
                onChange={(v) => set('speed_baseline_hours', v)}
              />
              <NumberField
                label="Текущая скорость — средняя за"
                suffix="мин"
                min={1}
                max={60}
                value={form.speed_window_minutes}
                onChange={(v) => set('speed_window_minutes', v)}
              />
              <NumberField
                label="Падение должно держаться"
                suffix="мин"
                min={0}
                max={240}
                value={form.speed_confirm_minutes}
                onChange={(v) => set('speed_confirm_minutes', v)}
                hint="Защита от коротких провалов"
              />
              <NumberField
                label="Не следить за нодами с нормой меньше"
                suffix="Мбит/с"
                min={0}
                value={form.speed_min_baseline_mbps}
                onChange={(v) => set('speed_min_baseline_mbps', v)}
                hint="На почти пустых нодах скорость скачет сама по себе"
              />
            </div>
          </Panel>

          <Panel title="Проверка IP после падения">
            <div className="form">
              <NumberField
                label="Сколько раз проверять IP"
                min={1}
                max={10}
                value={form.investigation_checks}
                onChange={(v) => set('investigation_checks', v)}
                hint="Бан — только если IP в бане во всех проверках. Если хоть раз доступен — проверка останавливается: скорость вернулась — «восстановилась», всё ещё низкая — «IP не в бане, но скорость ноды низкая»"
              />
              <NumberField
                label="Интервал между проверками"
                suffix="мин"
                min={1}
                max={720}
                value={form.investigation_interval_minutes}
                onChange={(v) => set('investigation_interval_minutes', v)}
              />
              <NumberField
                label="Пауза перед новой проверкой того же домена"
                suffix="мин"
                min={0}
                max={10080}
                value={form.investigation_cooldown_minutes}
                onChange={(v) => set('investigation_cooldown_minutes', v)}
              />
              <Toggle
                checked={form.auto_switch_enabled}
                onChange={(v) => set('auto_switch_enabled', v)}
                label="Автосмена IP (глобально)"
                hint="При подтверждённом бане менять A-запись на следующий доступный IP"
              />
            </div>
          </Panel>

          <Panel title="Ноды Remnawave">
            <div className="form">
              <NumberField
                label="Интервал опроса нод"
                suffix="сек"
                min={10}
                max={3600}
                value={form.node_poll_interval_seconds}
                onChange={(v) => set('node_poll_interval_seconds', v)}
                hint="Статус и скорость нод обновляются с этим интервалом"
              />
              <NumberField
                label="«Offline» / «снова online» — если держится"
                suffix="опросов подряд"
                min={1}
                max={60}
                value={form.node_offline_confirm_polls}
                onChange={(v) => set('node_offline_confirm_polls', v)}
                hint="Уведомление «нода offline» приходит один раз, следующее — когда нода снова online. Защита от коротких сбоев"
              />
              <Toggle
                checked={form.auto_import_nodes}
                onChange={(v) => set('auto_import_nodes', v)}
                label="Добавлять адреса нод в «Домены»"
                hint="Домен или IP новой ноды сам появится во вкладке «Домены»"
              />
            </div>
          </Panel>
        </div>
      )}

      {tab === 'sources' && (
        <>
          <Panel title="Общее">
            <div className="form">
              <label className="field">
                <span className="field__label">Порт для TCP-проверок (по умолчанию)</span>
                <input
                  className="input"
                  type="number"
                  min={1}
                  max={65535}
                  style={{ maxWidth: 160 }}
                  value={form.tcp_check_port ?? ''}
                  onChange={(e) => set('tcp_check_port', e.target.value === '' ? '' : Number(e.target.value))}
                />
                <span className="field__hint">
                  Порт инбаунда на нодах (обычно 443). У домена можно указать свой на его странице.
                </span>
              </label>
              <NumberField
                label="Пауза между проверками IP"
                suffix="мс"
                min={0}
                max={60000}
                value={form.checker_delay_ms}
                onChange={(v) => set('checker_delay_ms', v)}
                hint="Защита от лимитов на стороне сервисов"
              />
            </div>
          </Panel>

          <div className="sources">
            {meta.checkers.map((c) => {
              const enabled = form.enabled_checkers.includes(c.name);
              const Extra = SOURCE_SETTINGS[c.name];
              return (
                <section key={c.name} className={`card panel source ${enabled ? 'is-on' : ''}`}>
                  <div className="source__head">
                    <Toggle checked={enabled} onChange={(v) => toggleChecker(c.name, v)} label={c.title} />
                  </div>
                  <p className="field__hint">{c.description}</p>
                  {checkerStatus[c.name] && <p className="source__status">{checkerStatus[c.name]}</p>}
                  {enabled && Extra && <Extra form={form} set={set} />}
                </section>
              );
            })}
          </div>
        </>
      )}

      {tab === 'notify' && (
        <div className="settings-grid">
          <Panel
            wide
            title="Уведомления в Telegram"
            actions={
              <button
                type="button"
                className="btn btn--sm btn--ghost"
                disabled={!!testing}
                onClick={() => test('telegram')}
              >
                {testing === 'telegram' ? <Spinner size={16} /> : <IconSend size={16} />}
                <span>Тест</span>
              </button>
            }
          >
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
          </Panel>

          <Panel title="Ежедневная сводка">
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
                  style={{ maxWidth: 160 }}
                  value={form.daily_summary_time}
                  onChange={(e) => set('daily_summary_time', e.target.value)}
                />
              </label>
              <button type="button" className="btn btn--ghost" disabled={!!testing} onClick={() => test('summary')}>
                {testing === 'summary' ? <Spinner size={16} /> : <IconSend size={16} />}
                <span>Отправить сводку сейчас</span>
              </button>
            </div>
          </Panel>
        </div>
      )}

      {tab === 'system' && (
        <div className="settings-grid">
          <Panel title="Хранение">
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
          </Panel>
          <Panel title="О системе">
            <dl className="sysinfo">
              <div>
                <dt>Часовой пояс</dt>
                <dd>{status?.timezone}</dd>
              </div>
              <div>
                <dt>Пароль входа</dt>
                <dd>задаётся в .env (APP_PASSWORD)</dd>
              </div>
            </dl>
          </Panel>
        </div>
      )}

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
