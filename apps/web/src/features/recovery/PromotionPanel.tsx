import { useEffect, useState } from "react";
import { proposalEvidence } from "./api";
import { Evidence, Field } from "./Fields";
import { stateLabel, type Text } from "./messages";
import type { ProposalEvidence, Receipt } from "./types";
import type { Channel } from "./useRecovery";
import { usePrivateValue } from "./usePrivateValue";
export function PromotionPanel({
  channel,
  text,
  proposalId,
  onProposalId,
  onReceipt,
}: {
  channel: Channel;
  text: Text;
  proposalId: string;
  onProposalId: (id: string) => void;
  onReceipt: (value: Receipt) => void;
}) {
  const [view, setView] = usePrivateValue<ProposalEvidence>(channel),
    [ceremony, setCeremony] = useState(""),
    [now, setNow] = useState(Date.now());
  useEffect(() => {
    const timer = window.setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(timer);
  }, []);
  const promotion = view?.promotion,
    expiry = promotion?.expires_at,
    expired = !!expiry && Date.parse(expiry) <= now;
  const reviewer = ["security", "governance"].includes(channel.role ?? "");
  function record(receipt: Receipt) {
    setView(null);
    setCeremony("");
    onReceipt(receipt);
  }
  return (
    <section aria-labelledby="recovery-proposal">
      <h2 id="recovery-proposal">{text.proposal}</h2>
      <p>{text.reviewNotice}</p>
      <form
        onSubmit={(e) => {
          e.preventDefault();
          void channel.run(async (signal) =>
            setView(await proposalEvidence(proposalId, signal), signal),
          );
        }}
      >
        <fieldset disabled={channel.disabled}>
          <Field
            id="recovery-proposal-id"
            label={text.proposalId}
            value={proposalId}
            onChange={(value) => {
              onProposalId(value);
              setView(null);
            }}
          />
          <button>{text.loadProposal}</button>
        </fieldset>
      </form>
      {view && promotion && (
        <div>
          <dl>
            <dt>{text.proposalId}</dt>
            <dd>{promotion.id}</dd>
            <dt>{text.revision}</dt>
            <dd>{promotion.revision}</dd>
            <dt>{text.binding}</dt>
            <dd>
              <code>{promotion.binding_digest}</code>
            </dd>
            <dt>{text.state}</dt>
            <dd>{stateLabel(promotion.state, text)}</dd>
            {expiry && (
              <>
                <dt>{text.expires}</dt>
                <dd>
                  <time dateTime={expiry}>{expiry}</time>
                </dd>
              </>
            )}
          </dl>
          <Evidence binding={view.binding} text={text} />
          <p>{text.current}</p>
          {expired && <p role="alert">{text.expired}</p>}
          {promotion.state !== "smoke_verified" && <p>{text.restricted}</p>}
          {reviewer && (
            <form
              onSubmit={(e) => {
                e.preventDefault();
                channel.command(
                  {
                    path: "/v1/recovery/promotions/approve",
                    input: "PromotionApprove",
                    output: "CommandResult",
                    body: {
                      proposal_id: promotion.id,
                      exact_binding_digest: promotion.binding_digest,
                      ceremony_id: ceremony,
                      expires_at: new Date(Date.now() + 300000).toISOString(),
                    },
                  },
                  record,
                );
              }}
            >
              <fieldset
                disabled={channel.disabled || promotion.state !== "proposed"}
              >
                <Field
                  id="recovery-ceremony"
                  label={text.ceremony}
                  value={ceremony}
                  onChange={setCeremony}
                />
                <button>{text.approve}</button>
              </fieldset>
            </form>
          )}
          <p>{text.approveNotice}</p>
          {channel.role === "operator" && (
            <button
              disabled={
                channel.disabled ||
                promotion.state !== "approved" ||
                !promotion.approval_id ||
                !expiry ||
                expired
              }
              onClick={() =>
                channel.command(
                  {
                    path: "/v1/recovery/promotions/execute",
                    input: "PromotionExecute",
                    output: "CommandResult",
                    body: {
                      proposal_id: promotion.id,
                      approval_id: promotion.approval_id,
                      exact_binding_digest: promotion.binding_digest,
                      expected_serving_generation: (
                        BigInt(view.binding.serving_generation) - 1n
                      ).toString(),
                    },
                  },
                  record,
                )
              }
            >
              {text.execute}
            </button>
          )}
        </div>
      )}
    </section>
  );
}
