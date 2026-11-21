import { uuidPattern } from "./api";
export function Field({
  id,
  label,
  value,
  onChange,
  type = "text",
  required = true,
  disabled = false,
  identifier = false,
  pattern,
}: {
  id: string;
  label: string;
  value: string;
  onChange: (value: string) => void;
  type?: string;
  required?: boolean;
  disabled?: boolean;
  identifier?: boolean;
  pattern?: string;
}) {
  return (
    <div>
      <label htmlFor={id}>{label}</label>
      <input
        id={id}
        type={type}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        required={required}
        disabled={disabled}
        autoComplete="off"
        {...(identifier
          ? { pattern: uuidPattern }
          : pattern
            ? { pattern }
            : {})}
      />
    </div>
  );
}
