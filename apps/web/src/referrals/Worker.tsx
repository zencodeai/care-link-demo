import { useEffect, useState, type FormEvent } from "react";
import {
  read,
  write,
  identifierPattern,
  type Output,
  type SourcePage,
} from "./api";
import { DeliveryState, Payload, Provenance } from "./Payload";
import type { DirectoryPage } from "../plans/api";
import { useCommand } from "./useCommand";
import type { Actions, Work } from "./useActions";
import { label, type Text } from "./messages";
import type {
  Consent,
  Context,
  Conversation,
  DirectoryEntry,
  Dispatch,
  Receipt,
  Referral,
} from "./types";
type SourceOption = SourcePage["items"][number];
export function Worker({ actions, text }: { actions: Actions; text: Text }) {
  const [sid, setSid] = useState("");
  const [conversation, setConversation] = useState<Conversation | null>(null);
  const [sources, setSources] = useState<SourceOption[]>([]);
  const [selected, setSelected] = useState<number[]>([]);
  const [serviceId, setServiceId] = useState("");
  const [options, setOptions] = useState<DirectoryPage | null>(null);
  const [service, setService] = useState<DirectoryEntry | null>(null);
  const [referralId, setReferralId] = useState("");
  const [context, setContext] = useState<Context | null>(null);
  const [consentId, setConsentId] = useState("");
  const [consent, setConsent] = useState<Consent | null>(null);
  const [dispatchId, setDispatchId] = useState("");
  const [dispatch, setDispatch] = useState<Dispatch | null>(null);
  const [receipt, setReceipt] = useState<Receipt | null>(null);
  const [reviewExpiry, setReviewExpiry] = useState(() =>
    new Date(Date.now() + 240000).toISOString(),
  );
  const commands = useCommand(actions);
  useEffect(() => {
    setContext(null);
    setConsent(null);
    setReceipt(null);
    setDispatch(null);
    setConversation(null);
    setSources([]);
    setOptions(null);
  }, [actions.failureEpoch]);
  const disabled = actions.busy || !actions.session;
  const visible = actions.notice === "done" && !actions.busy;
  const draft = context?.referral;
  const [now, setNow] = useState(Date.now());
  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(timer);
  }, []);
  const validConsent = !!(
    consent &&
    draft &&
    !consent.revoked_at &&
    Date.parse(consent.effective_at) <= now &&
    Date.parse(consent.expires_at) > now &&
    consent.scope.session_id === draft.payload.session_id &&
    consent.scope.subject_id === draft.payload.subject_id &&
    consent.scope.purpose === "referral" &&
    consent.recipient.kind === "service" &&
    consent.recipient.service_id === draft.payload.recipient_service_id &&
    draft.payload.fields.every((field) =>
      consent.scope.fields.includes(field.field),
    )
  );
  const validReview = !!(
    context?.review &&
    draft &&
    context.review.decision === "accept" &&
    context.review.exact_digest === draft.digest &&
    Date.parse(context.review.expires_at) > now
  );

  const refresh = async (id: string, signal: AbortSignal) => {
    const current = await read(
      `/v1/referrals/${id}/context`,
      "ReferralContext",
      signal,
    );
    setContext(current);
    setReferralId(current.referral.id);
    if (current.referral.dispatch_id) {
      setDispatchId(current.referral.dispatch_id);
      setDispatch(
        await read(
          `/v1/dispatches/${current.referral.dispatch_id}`,
          "DispatchView",
          signal,
        ),
      );
    }
  };
  const command = (
    path: string,
    input: string,
    output: Output,
    body: unknown,
    apply: (result: unknown, signal: AbortSignal) => Promise<void> | void,
  ) => {
    commands.send({ path, input, output, body }, apply);
  };
  const perform = (event: FormEvent, work: Work) => {
    event.preventDefault();
    void actions.run(work);
  };
  const sourceKey = (option: SourceOption) =>
    `${option.selected.field}:${option.selected.source.id}:${option.selected.source.revision}`;
  return (
    <>
      <section aria-labelledby="worker-title">
        <h2 id="worker-title">{text.worker}</h2>
        <form
          onSubmit={(event) =>
            perform(event, async (signal) => {
              const current = await read(
                `/v1/sessions/${sid}`,
                "SessionView",
                signal,
              );
              const page = await read(
                `/v1/sessions/${sid}/referral-sources`,
                "ReferralSourcePage",
                signal,
              );
              setConversation(current);
              setSources(page.items);
              setSelected([]);
              setContext(null);
              setConsent(null);
              setDispatch(null);
              setReceipt(null);
            })
          }
        >
          <label htmlFor="referral-session">{text.session}</label>
          <input
            id="referral-session"
            value={sid}
            required
            pattern={identifierPattern}
            onChange={(event) => setSid(event.target.value)}
            disabled={disabled}
          />
          <button disabled={disabled}>{text.load}</button>
        </form>
        <div className="actions">
          <button
            disabled={disabled}
            onClick={() =>
              void actions.run(async (signal) => {
                setOptions(
                  await write(
                    {
                      key: crypto.randomUUID(),
                      path: "/v1/directory/search",
                      input: "DirectoryQuery",
                      output: "DirectoryPage",
                      body: {
                        jurisdiction: null,
                        locale: text.language === "Langue" ? "fr-CA" : "en-CA",
                        need: "navigation",
                      },
                    },
                    signal,
                  ),
                );
              })
            }
          >
            {text.findOptions}
          </button>
          {visible && options?.next_cursor && (
            <button
              disabled={disabled}
              onClick={() =>
                void actions.run(async (signal) => {
                  setOptions(
                    await write(
                      {
                        key: crypto.randomUUID(),
                        path: "/v1/directory/search",
                        input: "DirectoryQuery",
                        output: "DirectoryPage",
                        body: {
                          jurisdiction: null,
                          locale:
                            text.language === "Langue" ? "fr-CA" : "en-CA",
                          need: "navigation",
                          cursor: options.next_cursor,
                        },
                      },
                      signal,
                    ),
                  );
                })
              }
            >
              {text.moreOptions}
            </button>
          )}
        </div>
        {visible && options && (
          <>
            <label htmlFor="receiving-options">{text.chooseOption}</label>
            <select
              id="receiving-options"
              value={serviceId}
              disabled={disabled}
              onChange={(event) => {
                const selected = options.items.find(
                  (item) => item.id === event.target.value,
                );
                setServiceId(selected?.id ?? "");
                setService(selected ?? null);
              }}
            >
              <option value="">—</option>
              {options.items.map((item) => (
                <option key={item.id} value={item.id}>
                  {item.facts.name} · {label(item.state, text)}
                </option>
              ))}
            </select>
          </>
        )}
        <form
          onSubmit={(event) =>
            perform(event, async (signal) => {
              setService(
                await read(
                  `/v1/directory/${serviceId}`,
                  "DirectoryView",
                  signal,
                ),
              );
            })
          }
        >
          <label htmlFor="referral-service">{text.service}</label>
          <input
            id="referral-service"
            value={serviceId}
            required
            pattern={identifierPattern}
            onChange={(event) => {
              setServiceId(event.target.value);
              setService(null);
            }}
            disabled={disabled}
          />
          <button disabled={disabled}>{text.loadService}</button>
        </form>
        {visible && service && (
          <div>
            <h3>{service.facts.name}</h3>
            <p>
              {text.state}: {label(service.state, text)} ·{" "}
              {label(service.facts.operating_state, text)} ·{" "}
              {label(service.facts.availability, text)}
            </p>
            <p>{service.facts.hours_description}</p>
            <p>
              {text.qualifications}:{" "}
              {label(service.facts.police_involvement, text)}
            </p>
            <ul>
              {service.facts.qualifications.map((item, index) => (
                <li key={index}>{item}</li>
              ))}
            </ul>
            <p>
              {text.alternative}:{" "}
              {service.facts.alternative_service_id ?? text.noAlternative}
            </p>
            <p>
              {text.expiry}: {service.expires_at}
            </p>
          </div>
        )}
        {visible && conversation && (
          <>
            <p>
              {text.subject}: {conversation.subject_id} · {text.revision}:{" "}
              {conversation.revision}
            </p>
            <fieldset disabled={disabled}>
              <legend>{text.sources}</legend>
              {sources.length ? (
                sources.map((option, index) => (
                  <div key={sourceKey(option)} className="referral-source">
                    <label>
                      <input
                        type="checkbox"
                        checked={selected.includes(index)}
                        onChange={(event) =>
                          setSelected((old) =>
                            event.target.checked
                              ? [...old, index]
                              : old.filter((value) => value !== index),
                          )
                        }
                      />
                      {label(option.selected.field, text)} ·{" "}
                      {option.field.value.kind === "text"
                        ? option.field.value.text
                        : option.field.value.kind === "choice"
                          ? option.field.value.value
                          : `${text.unknownValue}: ${label(option.field.value.reason, text)}`}
                    </label>
                    <Provenance sources={option.field.sources} text={text} />
                  </div>
                ))
              ) : (
                <p>{text.noSelection}</p>
              )}
            </fieldset>
            <p>{text.draftHint}</p>
            <button
              disabled={
                disabled ||
                !service ||
                !selected.length ||
                !conversation.subject_id ||
                !!commands.pending
              }
              onClick={() => {
                if (!service || !conversation.subject_id) return;
                command(
                  `/v1/sessions/${conversation.id}/referrals`,
                  "ReferralDraftCreate",
                  "ReferralView",
                  {
                    expected_revision: conversation.revision,
                    subject_id: conversation.subject_id,
                    recipient_service_id: service.id,
                    directory_revision: service.revision,
                    purpose: "referral",
                    selected: sources
                      .filter((_option, index) => selected.includes(index))
                      .map((option) => option.selected),
                  },
                  async (result, signal) => {
                    const value = result as Referral;
                    await refresh(value.id, signal);
                    setDispatch(null);
                    setReceipt(null);
                  },
                );
              }}
            >
              {text.draft}
            </button>
          </>
        )}
        <form
          onSubmit={(event) =>
            perform(event, async (signal) => {
              await refresh(referralId, signal);
              commands.clear();
            })
          }
        >
          <label htmlFor="open-referral">{text.open}</label>
          <input
            id="open-referral"
            value={referralId}
            required
            pattern={identifierPattern}
            onChange={(event) => setReferralId(event.target.value)}
            disabled={disabled}
          />
          <button disabled={disabled}>{text.openReferral}</button>
        </form>
      </section>
      {visible && draft && (
        <section aria-labelledby="referral-review-title">
          <h2 id="referral-review-title">{text.review}</h2>
          <p>
            {text.generation}: {draft.generation} · {text.revision}:{" "}
            {draft.revision} · {text.state}: {label(draft.state, text)}
          </p>
          <p className="referral-digest">
            {text.digest}: {draft.digest}
          </p>
          <Payload payload={draft.payload} text={text} />
          <p>{text.reviewHint}</p>
          <p>{text.revise}</p>
          <form
            onSubmit={(event) =>
              perform(event, async (signal) => {
                setConsent(
                  await read(
                    `/v1/consents/${consentId}`,
                    "ConsentView",
                    signal,
                  ),
                );
                await refresh(draft.id, signal);
              })
            }
          >
            <label htmlFor="referral-consent">{text.consent}</label>
            <input
              id="referral-consent"
              value={consentId}
              required
              pattern={identifierPattern}
              onChange={(event) => {
                setConsentId(event.target.value);
                setConsent(null);
              }}
              disabled={disabled}
            />
            <button disabled={disabled}>{text.loadConsent}</button>
          </form>
          <p>{text.consentHint}</p>
          {consent ? (
            <dl>
              <dt>{text.recipient}</dt>
              <dd>{consent.scope.recipient_id}</dd>
              <dt>{text.purpose}</dt>
              <dd>{label(consent.scope.purpose, text)}</dd>
              <dt>{text.selected}</dt>
              <dd>
                {consent.scope.fields
                  .map((field) => label(field, text))
                  .join(", ")}
              </dd>
              <dt>{text.expiry}</dt>
              <dd>{consent.expires_at}</dd>
              <dt>{text.revoked}</dt>
              <dd>{consent.revoked_at ?? "—"}</dd>
            </dl>
          ) : (
            <p>{text.consentMissing}</p>
          )}
          <label htmlFor="review-expiry">{text.reviewExpiry}</label>
          <input
            id="review-expiry"
            value={reviewExpiry}
            onChange={(event) => setReviewExpiry(event.target.value)}
            disabled={disabled}
          />
          <div className="actions">
            {(["accept", "reject"] as const).map((decision) => (
              <button
                key={decision}
                disabled={disabled || !!commands.pending}
                onClick={() =>
                  command(
                    `/v1/referrals/${draft.id}/review`,
                    "ReviewCommand",
                    "ReviewView",
                    {
                      expected_revision: draft.revision,
                      draft_id: draft.id,
                      exact_digest: draft.digest,
                      source_vector: context.versions,
                      decision,
                      edited_text: null,
                      expires_at: reviewExpiry,
                    },
                    async (_result, signal) => {
                      await refresh(draft.id, signal);
                    },
                  )
                }
              >
                {decision === "accept" ? text.approve : text.reject}
              </button>
            ))}
          </div>
          {context.review && (
            <p>
              {text.review}: {label(context.review.decision, text)} ·{" "}
              {text.expiry}: {context.review.expires_at} ·{" "}
              {context.review.reviewer_id}
            </p>
          )}
          <button
            disabled={
              disabled || !validReview || !validConsent || !!commands.pending
            }
            onClick={() => {
              if (!context.review || !consent) return;
              command(
                `/v1/referrals/${draft.id}/dispatch`,
                "DispatchRequest",
                "DispatchView",
                {
                  expected_revision: draft.revision,
                  consent_id: consent.id,
                  review_id: context.review.id,
                  exact_payload_digest: draft.digest,
                  generation: draft.generation,
                },
                (result) => {
                  const value = result as Dispatch;
                  setDispatch(value);
                  setDispatchId(value.dispatch_id);
                  setReceipt(null);
                },
              );
            }}
          >
            {text.enqueue}
          </button>
          <p>{text.freshOnly}</p>
        </section>
      )}
      <section aria-labelledby="dispatch-title">
        <h2 id="dispatch-title">{text.dispatch}</h2>
        <form
          onSubmit={(event) =>
            perform(event, async (signal) => {
              setDispatch(
                await read(
                  `/v1/dispatches/${dispatchId}`,
                  "DispatchView",
                  signal,
                ),
              );
              setReceipt(null);
              commands.clear();
            })
          }
        >
          <label htmlFor="open-dispatch">{text.dispatch}</label>
          <input
            id="open-dispatch"
            value={dispatchId}
            required
            pattern={identifierPattern}
            onChange={(event) => setDispatchId(event.target.value)}
            disabled={disabled}
          />
          <button disabled={disabled}>{text.loadDispatch}</button>
        </form>
        {visible && dispatch && (
          <>
            <p className="referral-digest">{dispatch.dispatch_id}</p>
            <p>
              {text.state}: {label(dispatch.state, text)} · {text.attempts}:{" "}
              {dispatch.attempt_count}
            </p>
            <DeliveryState state={dispatch.state} text={text} />
            {dispatch.state === "pending" && (
              <button
                disabled={disabled || !!commands.pending}
                onClick={() =>
                  command(
                    `/v1/dispatches/${dispatch.dispatch_id}/send`,
                    "RevisionCommand",
                    "DispatchView",
                    { expected_revision: dispatch.revision },
                    (result) => {
                      setDispatch(result as Dispatch);
                      setReceipt(null);
                    },
                  )
                }
              >
                {text.send}
              </button>
            )}
            <button
              disabled={disabled || !!commands.pending}
              onClick={() =>
                command(
                  `/v1/dispatches/${dispatch.dispatch_id}/reconcile`,
                  "RevisionCommand",
                  "DispatchView",
                  { expected_revision: dispatch.revision },
                  (result) => {
                    setDispatch(result as Dispatch);
                    setReceipt(null);
                  },
                )
              }
            >
              {text.reconcile}
            </button>
            <button
              disabled={disabled}
              onClick={() =>
                void actions.run(async (signal) => {
                  setReceipt(
                    await read(
                      `/v1/dispatches/${dispatch.dispatch_id}/receipt`,
                      "ReceiptView",
                      signal,
                    ),
                  );
                })
              }
            >
              {text.receipt}
            </button>
          </>
        )}
        {visible && receipt && (
          <div>
            <h3>{text.receipt}</h3>
            <p>
              {text.state}: {label(receipt.status, text)} ·{" "}
              {receipt.observed_at}
            </p>
            <p>
              {text.acceptedFields}:{" "}
              {receipt.accepted_fields
                .map((field) => label(field, text))
                .join(", ") || "—"}
            </p>
            <p className="referral-digest">{receipt.payload_digest}</p>
          </div>
        )}
        <p className="notice">{text.support}</p>
      </section>
      {commands.pending && !actions.busy && (
        <p role="status" className="referral-digest">
          {text.unknown} {commands.pending.key}
          <button disabled={disabled} onClick={commands.retry}>
            {text.resume}
          </button>
        </p>
      )}
    </>
  );
}
