import type { ReactNode } from "react";
export function Field({
  id,
  label,
  value,
  onChange,
  type = "text",
  required = true,
  pattern,
}: {
  id: string;
  label: string;
  value: string;
  onChange: (value: string) => void;
  type?: string;
  required?: boolean;
  pattern?: string;
}) {
  return (
    <div>
      <label htmlFor={id}>{label}</label>
      <input
        id={id}
        value={value}
        type={type}
        required={required}
        autoComplete="off"
        onChange={(e) => onChange(e.target.value)}
        {...(pattern ? { pattern } : {})}
      />
    </div>
  );
}
export function Select({
  id,
  label,
  value,
  onChange,
  children,
}: {
  id: string;
  label: string;
  value: string;
  onChange: (value: string) => void;
  children: ReactNode;
}) {
  return (
    <div>
      <label htmlFor={id}>{label}</label>
      <select id={id} value={value} onChange={(e) => onChange(e.target.value)}>
        {children}
      </select>
    </div>
  );
}
export const digestPattern = "[0-9a-f]{64}";
export const uuidPattern =
  "[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}";
