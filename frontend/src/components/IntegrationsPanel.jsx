import { useEffect, useState } from 'react';
import { settingsApi } from '../api/index.js';
import Badge from './Badge.jsx';
import { IconCheck, IconX } from './Icons.jsx';
import Spinner from './Spinner.jsx';
import { useToast } from './Toast.jsx';

// необязательные поля — без них интеграция всё равно считается настроенной
const OPTIONAL = ['remnawave_api_key', 'cloudflare_account_id'];

const SOURCE_LABEL = {
  panel: { text: 'из панели', tone: 'ok' },
  env: { text: 'из .env', tone: 'muted' },
  none: { text: 'не задано', tone: 'warn' },
};

function IntegrationCard({ group, title, fields, onSaved }) {
  const toast = useToast();
  const [draft, setDraft] = useState({});
  const [busy, setBusy] = useState(false);
  const [test, setTest] = useState(null); // {ok, message} | 'loading'

  const configured = fields.every((f) => f.is_set || OPTIONAL.includes(f.key));
  const dirty = Object.values(draft).some((v) => v !== undefined);

  const save = async (values) => {
    setBusy(true);
    try {
      const res = await settingsApi.updateIntegrations(values);
      setDraft({});
      setTest(null);
      onSaved(res);
      toast.success(`${title}: сохранено`);
    } catch (e) {
      toast.error(e.message);
    } finally {
      setBusy(false);
    }
  };

  const runTest = async () => {
    setTest('loading');
    try {
      setTest(await settingsApi.testIntegration(group));
    } catch (e) {
      setTest({ ok: false, message: e.message });
    }
  };

  return (
    <section className="card panel integration">
      <div className="panel__head">
        <h2 className="panel__title">{title}</h2>
        {configured ? <Badge tone="ok">Настроено</Badge> : <Badge tone="warn">Не настроено</Badge>}
      </div>

      <div className="form">
        {fields.map((f) => {
          const src = SOURCE_LABEL[f.source];
          const value = draft[f.key];
          return (
            <label key={f.key} className="field">
              <span className="field__label integration__label">
                {f.title}
                <span className={`integration__src text-${src.tone}`}>{src.text}</span>
              </span>
              <div className="integration__row">
                <input
                  className="input mono"
                  type={f.secret ? 'password' : 'text'}
                  autoComplete="off"
                  spellCheck={false}
                  placeholder={f.secret ? (f.is_set ? `${f.value} — введите новый, чтобы заменить` : 'не задан') : f.hint}
                  value={value ?? (f.secret ? '' : f.value)}
                  onChange={(e) => setDraft((d) => ({ ...d, [f.key]: e.target.value }))}
                />
                {f.source === 'panel' && (
                  <button
                    type="button"
                    className="icon-btn icon-btn--danger"
                    title="Удалить значение из панели (вернуться к .env)"
                    disabled={busy}
                    onClick={() => save({ [f.key]: '' })}
                  >
                    <IconX size={18} />
                  </button>
                )}
              </div>
              {f.hint && f.secret && <span className="field__hint">{f.hint}</span>}
            </label>
          );
        })}
      </div>

      {test && test !== 'loading' && (
        <div className={`alert ${test.ok ? 'alert--ok' : 'alert--bad'}`}>
          {test.ok ? <IconCheck size={18} /> : <IconX size={18} />}
          <span>{test.message}</span>
        </div>
      )}

      <div className="integration__actions">
        <button type="button" className="btn btn--ghost btn--sm" onClick={runTest} disabled={busy || test === 'loading'}>
          {test === 'loading' ? <Spinner size={14} /> : null}
          <span>Проверить</span>
        </button>
        <button
          type="button"
          className="btn btn--primary btn--sm"
          disabled={busy || !dirty}
          onClick={() => {
            const values = {};
            Object.entries(draft).forEach(([k, v]) => {
              // пустое поле секрета = «не менять»
              const field = fields.find((f) => f.key === k);
              if (field.secret && v === '') return;
              values[k] = v;
            });
            save(values);
          }}
        >
          {busy ? 'Сохраняю…' : 'Сохранить'}
        </button>
      </div>
    </section>
  );
}

export default function IntegrationsPanel({ onChanged }) {
  const [data, setData] = useState(null);
  const [error, setError] = useState('');

  useEffect(() => {
    settingsApi
      .integrations()
      .then(setData)
      .catch((e) => setError(e.message));
  }, []);

  if (error) return <div className="alert alert--bad">{error}</div>;
  if (!data) return <Spinner size={22} />;

  return (
    <div className="integrations-grid">
      {Object.entries(data.groups).map(([group, title]) => (
        <IntegrationCard
          key={group}
          group={group}
          title={title}
          fields={data.fields.filter((f) => f.group === group)}
          onSaved={(res) => {
            setData(res);
            onChanged?.();
          }}
        />
      ))}
    </div>
  );
}
