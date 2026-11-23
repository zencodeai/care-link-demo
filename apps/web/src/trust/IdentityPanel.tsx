import { useEffect, useState, type ReactNode } from "react";
import { parseContract } from "@care-link/contracts";
import {
  authorizationUrl,
  decodeCeremony,
  decodeLogin,
  decodeProof,
  request,
  type Ceremony,
} from "./api";
import { type Channel } from "./channel";
import { type Locale, type Text } from "./messages";
const serviceRoles = [
  "pid",
  "carer",
  "professional_participant",
  "worker",
  "supervisor",
] as const;
const trainingRoles = ["trainer", "governance"] as const;
const returnRoutes = {
  pid: "participant",
  carer: "participant",
  professional_participant: "participant",
  worker: "workforce",
  supervisor: "workforce",
  trainer: "training",
  governance: "governance",
} as const;
type LoginRole = keyof typeof returnRoutes;
const uuid = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;
export function AccountPanel({
  channel,
  text,
  locale,
  id,
  title,
  oidcOrigin,
  navigate,
  children,
  training = false,
}: {
  channel: Channel;
  text: Text;
  locale: Locale;
  id: string;
  title: string;
  oidcOrigin: string | null;
  navigate: (url: string) => void;
  children?: ReactNode;
  training?: boolean;
}) {
  const [role, setRole] = useState<LoginRole>(training ? "trainer" : "pid");
  const roles: readonly LoginRole[] = training ? trainingRoles : serviceRoles;
  const labels: Record<LoginRole, string> = {
    pid: text.pid,
    carer: text.carer,
    professional_participant: text.professionalParticipant,
    worker: text.worker,
    supervisor: text.supervisor,
    trainer: text.trainer,
    governance: text.governance,
  };
  const { session, busy, notice, run, mutate, setSession } = channel;
  return (
    <section aria-labelledby={`${id}-title`}>
      <h3 id={`${id}-title`}>{title}</h3>
      <p role="status">
        {session && notice === "unchecked"
          ? `${text.active}: ${session.role} · ${text.assurance}: ${session.assurance}`
          : text[notice]}
      </p>
      {session && (
        <p>
          {text.expires}:{" "}
          <time dateTime={session.expires_at}>{session.expires_at}</time>
        </p>
      )}
      <div className="actions">
        <button
          type="button"
          disabled={busy}
          onClick={() => {
            void run(async (signal) => {
              await channel.loadSession(signal);
            });
          }}
        >
          {text.check}
        </button>
        {session && (
          <button
            type="button"
            disabled={busy}
            onClick={() => {
              void run(async (signal) => {
                await mutate("/v1/auth/logout", {}, signal, (raw) =>
                  parseContract("CommandResult", raw),
                );
                setSession(null);
              });
            }}
          >
            {text.signOut}
          </button>
        )}
      </div>
      <label htmlFor={`${id}-role`}>{text.role}</label>
      <select
        id={`${id}-role`}
        value={role}
        disabled={busy}
        onChange={(event) => {
          const next = roles.find((item) => item === event.target.value);
          if (next) setRole(next);
        }}
      >
        {roles.map((item) => (
          <option key={item} value={item}>
            {labels[item]}
          </option>
        ))}
      </select>
      <p className="hint">{text.roleHint}</p>
      {!oidcOrigin && <p>{text.oidcUnconfigured}</p>}
      <button
        type="button"
        disabled={busy || !oidcOrigin}
        onClick={() => {
          void run(async (signal) => {
            const intent = await mutate(
              "/v1/auth/login",
              {
                role,
                return_route: returnRoutes[role],
                locale,
              },
              signal,
              decodeLogin,
            );
            navigate(authorizationUrl(intent.authorization_url, oidcOrigin));
          });
        }}
      >
        {text.signIn}
      </button>
      {busy && <p role="status">{text.busy}</p>}
      {children}
    </section>
  );
}

export function Verification({
  channel,
  text,
  oidcOrigin,
  navigate,
}: {
  channel: Channel;
  text: Text;
  oidcOrigin: string | null;
  navigate: (url: string) => void;
}) {
  const [purpose, setPurpose] = useState<"export" | "delete" | "plan_view">(
    "plan_view",
  );
  const [resource, setResource] = useState("");
  const [view, setView] = useState<Ceremony | null>(null);
  const [badId, setBadId] = useState(false);
  const { session, busy, run, mutate, origin, completedCeremony } = channel;
  useEffect(() => {
    setView(null);
  }, [session]);
  return (
    <div className="verification">
      <h4>{text.stepUp}</h4>
      <p>{text.stepHint}</p>
      <label htmlFor="verification-purpose">{text.purpose}</label>
      <select
        id="verification-purpose"
        disabled={busy}
        value={purpose}
        onChange={(event) => {
          const value = event.target.value;
          if (value === "export" || value === "delete" || value === "plan_view")
            setPurpose(value);
          setView(null);
        }}
      >
        <option value="plan_view">{text.plan_view}</option>
        <option value="export">{text.export}</option>
        <option value="delete">{text.delete}</option>
      </select>
      <label htmlFor="verification-resource">{text.resource}</label>
      <input
        id="verification-resource"
        disabled={busy}
        value={resource}
        autoComplete="off"
        spellCheck={false}
        aria-invalid={badId}
        onChange={(event) => {
          setResource(event.target.value);
          setView(null);
          setBadId(false);
        }}
      />
      {badId && <p role="alert">{text.invalidId}</p>}
      <button
        type="button"
        disabled={busy || !session || !oidcOrigin}
        onClick={() => {
          if (!uuid.test(resource)) {
            setBadId(true);
            return;
          }
          setView(null);
          void run(async (signal) => {
            const ceremony = await mutate(
              "/v1/auth/step-up",
              {
                purpose,
                resource_id: resource,
                expected_revision: session?.revision,
              },
              signal,
              decodeCeremony,
            );
            setView(ceremony);
            if (ceremony.authorization_url)
              navigate(
                authorizationUrl(ceremony.authorization_url, oidcOrigin),
              );
          });
        }}
      >
        {text.startStep}
      </button>
      {completedCeremony && session && (
        <button
          type="button"
          disabled={busy}
          onClick={() => {
            void run(async (signal) => {
              const proof = decodeProof(
                await request(
                  origin,
                  `/v1/auth/step-up/proof?ceremony_id=${completedCeremony}`,
                  signal,
                ),
              );
              setView(
                await mutate(
                  "/v1/auth/step-up/confirm",
                  {
                    ceremony_id: completedCeremony,
                    proof_intent_id: proof,
                    expected_revision: session.revision,
                  },
                  signal,
                  decodeCeremony,
                ),
              );
            });
          }}
        >
          {text.confirmStep}
        </button>
      )}
      {view && (
        <p role="status">
          {text.ceremony}: {view.state} · {text.notBefore}:{" "}
          <time dateTime={view.not_before}>{view.not_before}</time>
        </p>
      )}
    </div>
  );
}
