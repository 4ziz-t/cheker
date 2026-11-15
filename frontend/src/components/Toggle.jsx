export default function Toggle({ checked, onChange, disabled, label, hint }) {
  return (
    <label className={`toggle ${disabled ? 'is-disabled' : ''}`}>
      <input
        type="checkbox"
        checked={!!checked}
        disabled={disabled}
        onChange={(e) => onChange(e.target.checked)}
      />
      <span className="toggle__track">
        <span className="toggle__thumb" />
      </span>
      {(label || hint) && (
        <span className="toggle__text">
          {label && <span className="toggle__label">{label}</span>}
          {hint && <span className="toggle__hint">{hint}</span>}
        </span>
      )}
    </label>
  );
}
