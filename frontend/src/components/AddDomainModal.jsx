import { useState } from 'react';
import { domainsApi } from '../api/index.js';
import { parseIpList } from '../utils/format.js';
import Modal from './Modal.jsx';
import Toggle from './Toggle.jsx';

export default function AddDomainModal({ onClose, onCreated }) {
  const [name, setName] = useState('');
  const [ipsText, setIpsText] = useState('');
  const [autoSwitch, setAutoSwitch] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');

  const { valid, invalid } = parseIpList(ipsText);

  const submit = async (e) => {
    e.preventDefault();
    if (invalid.length) {
      setError(`Некорректные IP: ${invalid.join(', ')}`);
      return;
    }
    setBusy(true);
    setError('');
    try {
      const domain = await domainsApi.create({ name: name.trim(), ips: valid, auto_switch: autoSwitch });
      onCreated(domain);
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <Modal
      title="Новый домен"
      onClose={onClose}
      footer={
        <>
          <button type="button" className="btn btn--ghost" onClick={onClose}>
            Отмена
          </button>
          <button type="submit" form="add-domain" className="btn btn--primary" disabled={busy || !name.trim()}>
            {busy ? 'Сохраняю…' : 'Добавить'}
          </button>
        </>
      }
    >
      <form id="add-domain" className="form" onSubmit={submit}>
        <label className="field">
          <span className="field__label">Домен</span>
          <input
            className="input mono"
            placeholder="de1.example.com"
            value={name}
            onChange={(e) => setName(e.target.value)}
            autoFocus
            autoCapitalize="none"
            spellCheck={false}
          />
          <span className="field__hint">Домен должен быть в зоне вашего аккаунта Cloudflare</span>
        </label>

        <label className="field">
          <span className="field__label">IP-адреса (по порядку переключения)</span>
          <textarea
            className="input mono"
            rows={6}
            placeholder={'1.2.3.4\n5.6.7.8\n9.10.11.12'}
            value={ipsText}
            onChange={(e) => setIpsText(e.target.value)}
            spellCheck={false}
          />
          <span className="field__hint">
            По одному на строку или через запятую. Распознано: {valid.length}
            {invalid.length > 0 && <span className="text-bad"> · ошибочных: {invalid.length}</span>}
          </span>
        </label>

        <Toggle
          checked={autoSwitch}
          onChange={setAutoSwitch}
          label="Автоматическая смена IP"
          hint="При бане текущего IP A-запись сменится на следующий доступный"
        />

        {error && <div className="alert alert--bad">{error}</div>}
      </form>
    </Modal>
  );
}
