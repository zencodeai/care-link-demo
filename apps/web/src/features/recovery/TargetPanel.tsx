import { useState } from "react";
import { read, targetEvidence } from "./api";
import { Evidence, Field } from "./Fields";
import { stateLabel, type Text } from "./messages";
import type { Backup, TargetEvidence, Receipt } from "./types";
import type { Channel } from "./useRecovery";
import { usePrivateValue } from "./usePrivateValue";
export function TargetPanel({
  channel,
  text,
  onProposal,
}: {
  channel: Channel;
  text: Text;
  onProposal: (receipt: Receipt) => void;
}) {
  const [backupId, setBackupId] = useState(""),
    [targetId, setTargetId] = useState("");
  const [backup, setBackup] = usePrivateValue<Backup>(channel),
    [current, setCurrent] = usePrivateValue<TargetEvidence>(channel);
  const operator = channel.role === "operator",
    target = current?.target;
  return (
    <section aria-labelledby="recovery-targets">
      <h2 id="recovery-targets">{text.targets}</h2>
      <p>{text.targetNotice}</p>
      {operator && (
        <div>
          <h3>{text.backups}</h3>
          <button
            disabled={channel.disabled}
            onClick={() =>
              channel.command(
                {
                  path: "/v1/recovery/backups",
                  input: "Empty",
                  output: "BackupView",
                  body: {},
                },
                (value) => {
                  setBackup(value);
                  setBackupId(value.id);
                },
              )
            }
          >
            {text.capture}
          </button>
          <form
            onSubmit={(e) => {
              e.preventDefault();
              void channel.run(async (signal) => {
                const value = await read(
                  `/v1/recovery/backups/${backupId}`,
                  "BackupView",
                  signal,
                );
                if (value.id !== backupId)
                  throw new Error("inconsistent backup");
                setBackup(value, signal);
              });
            }}
          >
            <fieldset disabled={channel.disabled}>
              <Field
                id="recovery-backup-id"
                label={text.backupId}
                value={backupId}
                onChange={setBackupId}
              />
              <button>{text.loadBackup}</button>
            </fieldset>
          </form>
          {backup && (
            <div>
              <dl>
                <dt>{text.backupId}</dt>
                <dd>{backup.id}</dd>
                <dt>{text.manifest}</dt>
                <dd>
                  <code>{backup.manifest_digest}</code>
                </dd>
                <dt>{text.captured}</dt>
                <dd>
                  <time dateTime={backup.capture_at}>{backup.capture_at}</time>
                </dd>
                <dt>{text.expires}</dt>
                <dd>
                  <time dateTime={backup.expires_at}>{backup.expires_at}</time>
                </dd>
                <dt>{text.schema}</dt>
                <dd>{backup.schema_version}</dd>
                <dt>{text.audit}</dt>
                <dd>
                  <code>{backup.audit_digest}</code>
                </dd>
                <dt>{text.state}</dt>
                <dd>{stateLabel(backup.state, text)}</dd>
              </dl>
              <button
                disabled={
                  channel.disabled ||
                  backup.state !== "verified" ||
                  Date.parse(backup.expires_at) <= Date.now()
                }
                onClick={() =>
                  channel.command(
                    {
                      path: "/v1/recovery/targets",
                      input: "RestoreCreate",
                      output: "RestoreView",
                      body: {
                        backup_id: backup.id,
                        manifest_digest: backup.manifest_digest,
                        expected_revision: "0",
                      },
                    },
                    (value) => {
                      setCurrent({ target: value, binding: null });
                      setTargetId(value.id);
                    },
                  )
                }
              >
                {text.restore}
              </button>
            </div>
          )}
        </div>
      )}
      <form
        onSubmit={(e) => {
          e.preventDefault();
          void channel.run(async (signal) =>
            setCurrent(await targetEvidence(targetId, signal), signal),
          );
        }}
      >
        <fieldset disabled={channel.disabled}>
          <Field
            id="recovery-target-id"
            label={text.targetId}
            value={targetId}
            onChange={setTargetId}
          />
          <button>{text.loadTarget}</button>
        </fieldset>
      </form>
      {target && (
        <div>
          <dl>
            <dt>{text.targetId}</dt>
            <dd>{target.id}</dd>
            <dt>{text.revision}</dt>
            <dd>{target.revision}</dd>
            <dt>{text.state}</dt>
            <dd>{stateLabel(target.state, text)}</dd>
            <dt>{text.head_digest}</dt>
            <dd>
              <code>{target.head.tip_digest}</code>
            </dd>
            <dt>{text.barrier}</dt>
            <dd>{target.head.restriction_barrier}</dd>
            <dt>{text.serving_generation}</dt>
            <dd>{target.serving_generation}</dd>
          </dl>
          {target.state !== "serving" && <p>{text.restricted}</p>}
          {operator && (
            <button
              disabled={
                channel.disabled ||
                !["quarantined", "validated", "promotion_pending"].includes(
                  target.state,
                )
              }
              onClick={() =>
                channel.command(
                  {
                    path: `/v1/recovery/targets/${target.id}/validate`,
                    input: "RevisionCommand",
                    output: "RestoreView",
                    body: { expected_revision: target.revision },
                  },
                  (value) => setCurrent({ target: value, binding: null }),
                )
              }
            >
              {text.validate}
            </button>
          )}
          {current.binding && (
            <Evidence binding={current.binding} text={text} />
          )}
          {operator && (
            <button
              disabled={
                channel.disabled ||
                target.state !== "validated" ||
                !current.binding
              }
              onClick={() => {
                const binding = current.binding;
                if (!binding) return;
                channel.command(
                  {
                    path: "/v1/recovery/promotions/propose",
                    input: "PromotionPropose",
                    output: "CommandResult",
                    body: {
                      target_id: target.id,
                      expected_revision: target.revision,
                      backup_digest: binding.backup_digest,
                      head_digest: binding.head_digest,
                      restriction_barrier: binding.restriction_barrier,
                      validation_digest: binding.validation_digest,
                      serving_generation: binding.serving_generation,
                      binding,
                    },
                  },
                  (receipt) => {
                    setCurrent(null);
                    onProposal(receipt);
                  },
                );
              }}
            >
              {text.propose}
            </button>
          )}
        </div>
      )}
    </section>
  );
}
