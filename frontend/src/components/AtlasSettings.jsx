export default function AtlasSettings({ form, set }) {
  const num = (key) => (e) => set(key, e.target.value === '' ? '' : Number(e.target.value));
  return (
    <div className="form">
      <p className="field__hint">
        Адрес проверяют три точки в России (разные сети) и контрольная точка в Европе. Если из Европы адрес
        открывается, а из России — нет, это бан. Если не открывается нигде — это не бан, а неработающий сервер:
        такая проверка не засчитывается. Адрес из реестра блокировок считается забаненным сразу.
      </p>
      <label className="field">
        <span className="field__label">Бан, когда из России не открывается</span>
        <div className="input-suffix">
          <input
            className="input"
            type="number"
            min={1}
            max={100}
            value={form.atlas_fail_percent ?? ''}
            onChange={num('atlas_fail_percent')}
          />
          <span>% точек и больше (50% — 2 из 3)</span>
        </div>
      </label>
      <label className="field">
        <span className="field__label">Ждать места в лимите сервиса не дольше</span>
        <div className="input-suffix">
          <input
            className="input"
            type="number"
            min={0}
            max={3600}
            value={form.atlas_max_wait_sec ?? ''}
            onChange={num('atlas_max_wait_sec')}
          />
          <span>секунд</span>
        </div>
        <span className="field__hint">
          У Red Atlas лимит — 6 живых проверок за 10 минут. Остальные IP ждут своей очереди; если ждать дольше —
          проверка этого IP считается неудачной и повторится в следующий раз.
        </span>
      </label>
    </div>
  );
}
