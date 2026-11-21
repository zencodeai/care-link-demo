import { usePrivateValue } from "./usePrivateValue";
import { useState } from "react";
import { digestPattern, Field, Select } from "./Fields";
import { list, read, utc } from "./api";
import type { Text } from "./messages";
import type { Artifact, ArtifactContext, Receipt } from "./types";
import type { Channel } from "./useGovernance";
import { Choices, State } from "./Labels";
export function Artifacts({ channel, text }: { channel: Channel; text: Text }) {
  const [kind, setKind] = useState("policy"),
    [version, setVersion] = useState(""),
    [digest, setDigest] = useState(""),
    [source, setSource] = useState(""),
    [content, setContent] = useState("technical"),
    [domain, setDomain] = useState("policy"),
    [signature, setSignature] = useState(""),
    [evidence, setEvidence] = useState("");
  const [artifact, setArtifact] = usePrivateValue<Artifact>(channel);
  const [changeClass, setChangeClass] = useState("C2"),
    [authority, setAuthority] = useState("technical"),
    [decision, setDecision] = useState("accept"),
    [expiry, setExpiry] = useState("");
  const [context, setContext] = usePrivateValue<ArtifactContext>(channel);
  const [receipt, setReceipt] = usePrivateValue<Receipt>(channel);
  return (
    <>
      {channel.role === "operator" && (
        <section aria-labelledby="artifact-title">
          <h2 id="artifact-title">{text.artifact}</h2>
          <form
            onSubmit={(e) => {
              e.preventDefault();
              channel.command(
                {
                  path: "/v1/artifacts",
                  input: "ArtifactRegister",
                  output: "ArtifactView",
                  body: {
                    kind,
                    version,
                    digest,
                    source_revision: source,
                    content_class: content,
                    population: "synthetic",
                    signature,
                    evidence_digests: list(evidence),
                    governed_domains: [domain],
                  },
                },
                setArtifact,
              );
            }}
          >
            <fieldset disabled={channel.disabled}>
              <Select
                id="artifact-kind"
                label={text.kind}
                value={kind}
                onChange={setKind}
              >
                <Choices
                  values={[
                    "release",
                    "policy",
                    "model",
                    "prompt",
                    "tool_registry",
                    "directory",
                    "content",
                    "config",
                    "scenario",
                    "migration",
                  ]}
                  text={text}
                />
              </Select>
              <Field
                id="artifact-version"
                label={text.version}
                value={version}
                onChange={setVersion}
              />
              <Field
                id="artifact-digest"
                label={text.digest}
                value={digest}
                onChange={setDigest}
                pattern={digestPattern}
              />
              <Field
                id="artifact-source"
                label={text.source}
                value={source}
                onChange={setSource}
              />
              <Select
                id="artifact-content"
                label={text.content}
                value={content}
                onChange={setContent}
              >
                <Choices
                  values={["technical", "stub", "reviewed_static"]}
                  text={text}
                />
              </Select>
              <Select
                id="artifact-domain"
                label={text.domain}
                value={domain}
                onChange={setDomain}
              >
                <Choices
                  values={[
                    "technical",
                    "triage",
                    "thresholds",
                    "consent",
                    "disclosure",
                    "emergency_guard",
                    "tool_permissions",
                    "triage_features",
                    "policy",
                    "prompt",
                    "model",
                    "protocol_content",
                    "directory",
                    "static_content",
                    "jurisdiction",
                    "infrastructure",
                  ]}
                  text={text}
                />
              </Select>
              <Field
                id="artifact-signature"
                label={text.signature}
                value={signature}
                onChange={setSignature}
              />
              <Field
                id="artifact-evidence"
                label={text.evidence}
                value={evidence}
                onChange={setEvidence}
                pattern={digestPattern}
              />
              <button>{text.register}</button>
            </fieldset>
          </form>
          {artifact && (
            <p>
              {text.registered}: <code>{artifact.digest}</code> ·{" "}
              <State value={artifact.state} text={text} />
            </p>
          )}
        </section>
      )}
      {["governance", "security"].includes(channel.role ?? "") && (
        <section aria-labelledby="artifact-review-title">
          <h2 id="artifact-review-title">{text.review}</h2>
          <p>{text.reviewHint}</p>
          <form
            onSubmit={(e) => {
              e.preventDefault();
              void channel.run(async (signal) => {
                const value = await read(
                  `/v1/artifacts/${digest}/review-context`,
                  "GovernanceArtifactContext",
                  signal,
                );
                if (value.artifact.digest !== digest)
                  throw new Error("context mismatch");
                if (signal.aborted) return;
                setContext(value, signal);
                setChangeClass(value.change_class);
              });
            }}
          >
            <fieldset disabled={channel.disabled}>
              <Field
                id="review-lookup"
                label={text.digest}
                value={digest}
                onChange={(value) => {
                  setDigest(value);
                  setContext(null);
                  setReceipt(null);
                }}
                pattern={digestPattern}
              />
              <button>{text.loadContext}</button>
            </fieldset>
          </form>
          {context && (
            <div>
              <dl>
                <dt>{text.digest}</dt>
                <dd>
                  <code>{context.artifact.digest}</code>
                </dd>
                <dt>{text.previousDigest}</dt>
                <dd>
                  <code>{context.previous_digest ?? text.notMeasured}</code>
                </dd>
                <dt>{text.source}</dt>
                <dd>
                  <code>{context.source_revision}</code>
                </dd>
                <dt>{text.payloadDigest}</dt>
                <dd>
                  <code>{context.payload_digest}</code>
                </dd>
                <dt>{text.changeClass}</dt>
                <dd>{context.change_class}</dd>
              </dl>
              <h3>{text.changedPaths}</h3>
              <ul>
                {context.changed_paths.map((path) => (
                  <li key={path}>
                    <code>{path}</code>
                  </li>
                ))}
              </ul>
              <h3>{text.domain}</h3>
              <ul>
                {context.governed_domains.map((domain) => (
                  <li key={domain}>
                    <State value={domain} text={text} />
                  </li>
                ))}
              </ul>
              <h3>{text.evidence}</h3>
              <ul>
                {context.evidence_digests.map((value) => (
                  <li key={value}>
                    <code>{value}</code>
                  </li>
                ))}
              </ul>
              <h3>{text.requiredReviews}</h3>
              <ul>
                {context.required_authorities.map((authority) => (
                  <li key={authority}>
                    <State value={authority} text={text} />
                  </li>
                ))}
              </ul>
              <h3>{text.missingReviews}</h3>
              {context.missing_authorities.length ? (
                <ul>
                  {context.missing_authorities.map((authority) => (
                    <li key={authority}>
                      <State value={authority} text={text} />
                    </li>
                  ))}
                </ul>
              ) : (
                <p>{text.noMissingReviews}</p>
              )}
            </div>
          )}
          <form
            onSubmit={(e) => {
              e.preventDefault();
              if (!context || context.artifact.digest !== digest) return;
              channel.command(
                {
                  path: "/v1/artifacts/reviews",
                  input: "ArtifactReview",
                  output: "CommandResult",
                  body: {
                    artifact_digest: context?.artifact.digest,
                    change_class: changeClass,
                    authority_class: authority,
                    decision,
                    evidence_digest: evidence,
                    expires_at: utc(expiry),
                  },
                },
                setReceipt,
              );
            }}
          >
            <fieldset disabled={channel.disabled}>
              <Select
                id="review-class"
                label={text.changeClass}
                value={changeClass}
                onChange={setChangeClass}
              >
                {["C0", "C1", "C2", "C3"].map((v) => (
                  <option key={v}>{v}</option>
                ))}
              </Select>
              <Select
                id="review-authority"
                label={text.authority}
                value={authority}
                onChange={setAuthority}
              >
                <Choices
                  values={[
                    "technical",
                    "security",
                    "privacy",
                    "operations",
                    "clinical",
                    "equity",
                    "community",
                  ]}
                  text={text}
                />
              </Select>
              <Select
                id="review-decision"
                label={text.decision}
                value={decision}
                onChange={setDecision}
              >
                <option value="accept">{text.accept}</option>
                <option value="reject">{text.reject}</option>
              </Select>
              <Field
                id="review-evidence"
                label={text.evidence}
                value={evidence}
                onChange={setEvidence}
                pattern={digestPattern}
              />
              <Field
                id="review-expiry"
                label={text.reviewExpiry}
                value={expiry}
                onChange={setExpiry}
                type="datetime-local"
              />
              <button disabled={!context || context.artifact.digest !== digest}>
                {text.submitReview}
              </button>
            </fieldset>
          </form>
          {receipt && (
            <p>
              {text.receipt}: <code>{receipt.resource_id}</code> ·{" "}
              {text.revision}: {receipt.revision}
            </p>
          )}
        </section>
      )}
    </>
  );
}
