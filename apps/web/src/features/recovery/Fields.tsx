import type { Binding } from "./types";
import type { Text } from "./messages";
export const uuidPattern =
  "[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}";
export function Field({
  id,
  label,
  value,
  onChange,
}: {
  id: string;
  label: string;
  value: string;
  onChange: (value: string) => void;
}) {
  return (
    <div>
      <label htmlFor={id}>{label}</label>
      <input
        id={id}
        value={value}
        required
        autoComplete="off"
        pattern={uuidPattern}
        onChange={(e) => onChange(e.target.value)}
      />
    </div>
  );
}
export function Evidence({ binding, text }: { binding: Binding; text: Text }) {
  return (
    <div>
      <h3>{text.evidence}</h3>
      <dl>
        {Object.entries(binding).map(([key, value]) => (
          <div key={key}>
            <dt>{text[key as keyof Binding]}</dt>
            <dd>
              <code>{value}</code>
            </dd>
          </div>
        ))}
      </dl>
    </div>
  );
}
