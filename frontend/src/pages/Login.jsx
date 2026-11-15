import { useState } from 'react';
import { authApi } from '../api/index.js';
import '../styles/login.css';

export default function Login({ onSuccess }) {
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);

  const submit = async (e) => {
    e.preventDefault();
    if (!password || busy) return;
    setBusy(true);
    setError('');
    try {
      await authApi.login(password);
      onSuccess();
    } catch (err) {
      setError(err.message);
      setPassword('');
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="login">
      <form className="login__card" onSubmit={submit}>
        <div className="login__brand">
          <span className="brand__mark" />
          <span>Cheker</span>
        </div>
        <p className="login__hint">Мониторинг нод и доменов</p>

        <label className="field">
          <span className="field__label">Пароль</span>
          <input
            className="input login__input"
            type="password"
            inputMode="text"
            autoComplete="current-password"
            maxLength={6}
            autoFocus
            value={password}
            onChange={(e) => setPassword(e.target.value.replace(/[^A-Za-z0-9]/g, ''))}
            placeholder="••••"
          />
        </label>

        {error && <div className="alert alert--bad">{error}</div>}

        <button type="submit" className="btn btn--primary btn--block" disabled={busy || password.length < 4}>
          {busy ? 'Проверяю…' : 'Войти'}
        </button>
      </form>
    </div>
  );
}
