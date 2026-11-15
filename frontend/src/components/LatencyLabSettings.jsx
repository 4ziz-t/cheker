import Toggle from './Toggle.jsx';

export default function LatencyLabSettings({ form, set }) {
  return (
    <div className="form">
      <Toggle
        checked={form.latencylab_throttle_is_ban}
        onChange={(v) => set('latencylab_throttle_is_ban', v)}
        label="Считать замедление ТСПУ баном"
        hint="Если Latency Lab видит throttling (обрыв/торможение после 16 КБ) — переключать IP"
      />
      <span className="field__hint">
        Проверяется порт из блока «Общее» (или порт, заданный у домена). Проверка идёт «с провода» в РФ через
        метод /api/lab/tspu.
      </span>
    </div>
  );
}
