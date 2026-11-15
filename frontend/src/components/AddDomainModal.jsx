import { useEffect, useState } from 'react';
import { domainsApi } from '../api/index.js';
import { isIPv4, parseIpList } from '../utils/format.js';
import Modal from './Modal.jsx';
import Spinner from './Spinner.jsx';
import Toggle from './Toggle.jsx';

const DOMAIN_RE = /^(?=.{1,253}$)(?!-)([a-z0-9-]{1,63}(?<!-)\.)+[a-z]{2,63}$/i;

const SOURCE_TEXT = { cloudflare: 'A-запись в Cloudflare', dns: 'DNS' };

export default function AddDomainModal({ onClose, onCreated }) {
  const [name, setName] = useState('');
  const [ipsText, setIpsText] = useState('');
  const [autoSwitch, setAutoSwitch] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [lookup, setLookup] = useState(null); // {loading} | {ip, source, kind}

  const clean = name.trim().toLowerCase().replace(/^https?:\/\//, '').split('/')[0].replace(/\.$/, '');
  const isIp = isIPv4(clean);
  const { valid, invalid } = parseIpList(ipsText);

  // определяем текущий IP домена, пока пользователь печатает
  useEffect(() => {
    setLookup(null);
    if (!clean || isIp || !DOMAIN_RE.test(clean)) return undefined;
    let cancelled = false;
    const t = setTimeout(async () => {
      setLookup({ loading: true });
      try {
        const res = await domainsApi.lookup(clean);
        if (!cancelled) setLookup(res);
      } catch {
        if (!cancelled) setLookup(null);
      }
    }, 600);
    return () => {
      cancelled = true;
      clearTimeout(t);
    };
  }, [clean, isIp]);

  const submit = async (e) => {
    e.preventDefault();
    if (invalid.length) {
      setError(`Некорректные IP: ${invalid.join(', ')}`);
      return;
    }
    setBusy(true);
    setError('');
    try {
      const domain = await domainsApi.create({
        name: clean,
        ips: isIp ? [] : valid,
        auto_switch: isIp ? false : autoSwitch,
      });
      onCreated(domain);
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  };

  const detected = lookup && !lookup.loading ? lookup.ip : null;
  const total = valid.length + (detected && !valid.includes(detected) ? 1 : 0);

  return (
    <Modal
      title="Новый домен или IP"
      onClose={onClose}
      footer={
        <>
          <button type="button" className="btn btn--ghost" onClick={onClose}>
            Отмена
          </button>
          <button type="submit" form="add-domain" className="btn btn--primary" disabled={busy || !clean}>
            {busy ? 'Сохраняю…' : 'Добавить'}
          </button>
        </>
      }
    >
      <form id="add-domain" className="form" onSubmit={submit}>
        <label className="field">
          <span className="field__label">Домен или IP</span>
          <input
            className="input mono"
            placeholder="de1.example.com"
            value={name}
            onChange={(e) => setName(e.target.value)}
            autoFocus
            autoCapitalize="none"
            spellCheck={false}
          />
          {isIp ? (
            <span className="field__hint">
              Это IP-адрес: он будет только проверяться на бан, менять нечего (нет A-записи).
            </span>
          ) : lookup?.loading ? (
            <span className="field__hint lookup">
              <Spinner size={12} /> Определяю текущий IP…
            </span>
          ) : lookup && detected ? (
            <span className="field__hint lookup">
              Текущий IP: <b className="mono text-ok">{detected}</b> ({SOURCE_TEXT[lookup.source] || lookup.source}) —
              будет добавлен в список автоматически
            </span>
          ) : lookup && !detected ? (
            <span className="field__hint text-warn">
              Текущий IP не найден: нет A-записи в Cloudflare и домен не резолвится
            </span>
          ) : (
            <span className="field__hint">Текущий IP домена определится автоматически</span>
          )}
        </label>

        {!isIp && (
          <>
            <label className="field">
              <span className="field__label">Резервные IP-адреса (по порядку переключения)</span>
              <textarea
                className="input mono"
                rows={5}
                placeholder={'1.2.3.4\n5.6.7.8'}
                value={ipsText}
                onChange={(e) => setIpsText(e.target.value)}
                spellCheck={false}
              />
              <span className="field__hint">
                По одному на строку или через запятую. Можно оставить пустым и добавить позже. Всего IP в списке
                будет: {total}
                {invalid.length > 0 && <span className="text-bad"> · ошибочных: {invalid.length}</span>}
              </span>
            </label>

            <Toggle
              checked={autoSwitch}
              onChange={setAutoSwitch}
              label="Автоматическая смена IP"
              hint="При бане текущего IP A-запись сменится на следующий доступный"
            />
          </>
        )}

        {error && <div className="alert alert--bad">{error}</div>}
      </form>
    </Modal>
  );
}
