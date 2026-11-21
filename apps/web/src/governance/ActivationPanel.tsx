import { usePrivateValue } from "./usePrivateValue";
import { useState } from "react";
import { Field, digestPattern, uuidPattern } from "./Fields";
import { list, read, utc } from "./api";
import type { Text } from "./messages";
import type { Activation, Health } from "./types";
import type { Channel } from "./useGovernance";
import { State } from "./Labels";
export function ActivationPanel({
  channel,
  text,
}: {
  channel: Channel;
  text: Text;
}) {
  const [health, setHealth] = usePrivateValue<Health>(channel),
    [activation, setActivation] = usePrivateValue<Activation>(channel);
  const [id, setId] = useState(""),
    [digest, setDigest] = useState(""),
    [effective, setEffective] = useState(""),
    [instances, setInstances] = useState("");
  const operator = channel.role === "operator";
  return (
    <section aria-labelledby="activation-title">
      <h2 id="activation-title">{text.activation}</h2>
      <p>{text.activationHint}</p>
      <p>{text.activationPolicyOnly}</p>
      {["operator", "security"].includes(channel.role ?? "") && (
        <>
          <button
            disabled={channel.disabled}
            onClick={() =>
              void channel.run(async (signal) =>
                setHealth(
                  await read("/v1/operations/health", "HealthView", signal),
                  signal,
                ),
              )
            }
          >
            {text.health}
          </button>
          {health && (
            <dl>
              <dt>{text.current}</dt>
              <dd>{health.epoch}</dd>
              <dt>{text.readiness}</dt>
              <dd>{health.ready ? text.readyYes : text.readyNo}</dd>
              <dt>{text.generation}</dt>
              <dd>{health.serving_generation}</dd>
              {health.reasons.map((reason) => (
                <dd key={reason}>{reason}</dd>
              ))}
            </dl>
          )}
        </>
      )}
      <form
        onSubmit={(e) => {
          e.preventDefault();
          void channel.run(async (signal) =>
            setActivation(
              await read(`/v1/activations/${id}`, "ActivationView", signal),
              signal,
            ),
          );
        }}
      >
        <fieldset disabled={channel.disabled}>
          <Field
            id="known-activation"
            label={text.knownActivation}
            value={id}
            onChange={setId}
            pattern={uuidPattern}
          />
          <button>{text.loadActivation}</button>
        </fieldset>
      </form>
      {operator && (
        <form
          onSubmit={(e) => {
            e.preventDefault();
            if (!health) return;
            channel.command(
              {
                path: "/v1/activations",
                input: "ActivationCreate",
                output: "ActivationView",
                body: {
                  artifact_digest: digest,
                  expected_epoch: health.epoch,
                  effective_at: utc(effective),
                  required_instances: list(instances),
                },
              },
              (value) => {
                setActivation(value);
                setId(value.id);
                setHealth(null);
              },
            );
          }}
        >
          <fieldset disabled={channel.disabled}>
            <Field
              id="activation-digest"
              label={text.digest}
              value={digest}
              onChange={setDigest}
              pattern={digestPattern}
            />
            <Field
              id="activation-effective"
              label={text.effective}
              value={effective}
              onChange={setEffective}
              type="datetime-local"
            />
            <Field
              id="activation-instances"
              label={text.instances}
              value={instances}
              onChange={setInstances}
            />
            <button disabled={!health}>{text.propose}</button>
          </fieldset>
        </form>
      )}
      {activation && (
        <div>
          <dl>
            <dt>{text.reference}</dt>
            <dd>
              <code>{activation.id}</code>
            </dd>
            <dt>{text.digest}</dt>
            <dd>
              <code>{activation.bundle_digest}</code>
            </dd>
            <dt>{text.desired}</dt>
            <dd>{activation.epoch}</dd>
            <dt>{text.state}</dt>
            <dd>
              <State value={activation.state} text={text} />
            </dd>
            <dt>{text.revision}</dt>
            <dd>{activation.revision}</dd>
          </dl>
          <h3>{text.missing}</h3>
          {activation.missing_instances.length ? (
            <ul>
              {activation.missing_instances.map((name) => (
                <li key={name}>{name}</li>
              ))}
            </ul>
          ) : (
            <p>{text.allAck}</p>
          )}
          {operator && (
            <button
              disabled={
                channel.disabled ||
                activation.state !== "ready" ||
                activation.missing_instances.length > 0
              }
              onClick={() =>
                channel.command(
                  {
                    path: `/v1/activations/${activation.id}/commit`,
                    input: "RevisionCommand",
                    output: "ActivationView",
                    body: { expected_revision: activation.revision },
                  },
                  (value) => {
                    setActivation(value);
                    setHealth(null);
                  },
                )
              }
            >
              {text.commit}
            </button>
          )}
        </div>
      )}
    </section>
  );
}
