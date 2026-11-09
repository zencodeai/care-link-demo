import { visit } from "jsonc-parser";
import compiledValidators from "./validators.generated.cjs";

export class ContractError extends Error {
  constructor() {
    super("Invalid contract input");
    this.name = "ContractError";
  }
}

export interface DeveloperCapability {
  contract_version: "dev-1";
  status: "developer_only";
  tags: { environment: "demo"; population: "synthetic" };
  participant_admission: false;
  business_operations: "unavailable";
  contract_validation: true;
}

// Compilation runs only in the offline generator. Runtime imports ordinary
// standalone functions so strict script-src CSP never needs unsafe-eval.
const validators = new Map<string, (value: unknown) => boolean>(
  Object.entries(compiledValidators),
);

function checkString(value: string): void {
  for (let index = 0; index < value.length; index += 1) {
    const code = value.charCodeAt(index);
    if (code >= 0xd800 && code <= 0xdbff) {
      const following = value.charCodeAt(index + 1);
      if (!(following >= 0xdc00 && following <= 0xdfff)) {
        throw new ContractError();
      }
      index += 1;
    } else if (code >= 0xdc00 && code <= 0xdfff) {
      throw new ContractError();
    }
  }
}

function checkJsonValue(value: unknown, ancestors = new Set<object>()): void {
  if (typeof value === "string") checkString(value);
  else if (typeof value === "number") {
    if (!Number.isFinite(value)) throw new ContractError();
  } else if (typeof value === "object" && value !== null) {
    if (ancestors.has(value)) throw new ContractError();
    ancestors.add(value);
    if (Array.isArray(value)) {
      for (const item of value) checkJsonValue(item, ancestors);
    } else {
      if (Object.getPrototypeOf(value) !== Object.prototype) {
        throw new ContractError();
      }
      for (const [key, item] of Object.entries(value)) {
        checkString(key);
        checkJsonValue(item, ancestors);
      }
    }
    ancestors.delete(value);
  } else if (value !== null && typeof value !== "boolean") {
    throw new ContractError();
  }
}

export function validateContract(name: string, value: unknown): void {
  const validator = validators.get(name);
  if (validator === undefined) throw new ContractError();
  try {
    checkJsonValue(value);
    if (!validator(value)) throw new ContractError();
  } catch {
    throw new ContractError();
  }
}

export function parseContract(name: string, raw: string): unknown {
  const objects: Set<string>[] = [];
  let invalid = false;
  try {
    visit(
      raw,
      {
        onObjectBegin: () => {
          objects.push(new Set<string>());
        },
        onObjectProperty: (key) => {
          const keys = objects.at(-1);
          if (keys === undefined || keys.has(key)) invalid = true;
          keys?.add(key);
        },
        onObjectEnd: () => {
          objects.pop();
        },
        onError: () => {
          invalid = true;
        },
      },
      { allowTrailingComma: false, disallowComments: true },
    );
    if (invalid) throw new ContractError();
    const value: unknown = JSON.parse(raw);
    validateContract(name, value);
    return value;
  } catch {
    throw new ContractError();
  }
}

export function parseCapability(raw: string): DeveloperCapability {
  // Validation establishes every required key and literal before this narrowing.
  return parseContract("DeveloperCapability", raw) as DeveloperCapability;
}
