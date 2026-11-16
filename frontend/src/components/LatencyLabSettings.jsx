export default function LatencyLabSettings({ form, set }) {
  return (
    <div className="form">
      <p className="field__hint">
        Главный признак — проверка «с провода» (wire): если по проводу IP недоступен, он считается заблокированным.
        Сначала используется метод /tspu, а если ключу он не разрешён — /multiscan.
      </p>
      <label className="field">
        <span className="field__label">Если wire не пришёл: бан, когда порт недоступен у</span>
        <div className="input-suffix">
          <input
            className="input"
            type="number"
            min={1}
            max={100}
            value={form.latencylab_fail_percent ?? ''}
            onChange={(e) => set('latencylab_fail_percent', e.target.value === '' ? '' : Number(e.target.value))}
          />
          <span>% мобильных операторов и более</span>
        </div>
      </label>
    </div>
  );
}
