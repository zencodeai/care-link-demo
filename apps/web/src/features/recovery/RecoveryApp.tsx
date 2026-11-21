import { useEffect, useState } from "react";
import { messages, stateLabel } from "./messages";
import { PromotionPanel } from "./PromotionPanel";
import { TargetPanel } from "./TargetPanel";
import type { Locale, Receipt } from "./types";
import { useRecovery } from "./useRecovery";
import { usePrivateValue } from "./usePrivateValue";
import "./styles.css";
export function RecoveryApp() {
  const [locale, setLocale] = useState<Locale>("en-CA"),
    [proposalId, setProposalId] = useState("");
  const channel = useRecovery(),
    text = messages[locale],
    [receipt, setReceipt] = usePrivateValue<Receipt>(channel);
  const role = channel.account?.role,
    supported = role && ["operator", "security", "governance"].includes(role);
  useEffect(() => {
    document.documentElement.lang = locale;
    document.title = text.title;
  }, [locale, text.title]);
  return (
    <main className="recovery-app">
      <header>
        <p className="eyebrow">CARE-Link</p>
        <h1>{text.title}</h1>
        <p>{text.scope}</p>
        <label htmlFor="recovery-language">{text.language}</label>
        <select
          id="recovery-language"
          value={locale}
          onChange={(e) =>
            setLocale(e.target.value === "fr-CA" ? "fr-CA" : "en-CA")
          }
        >
          <option value="en-CA">English</option>
          <option value="fr-CA">Français</option>
        </select>
      </header>
      <section aria-labelledby="recovery-account">
        <h2 id="recovery-account">{text.account}</h2>
        <a href="/">{text.signIn}</a>
        <p
          role={
            ["unchecked", "busy", "ready"].includes(channel.notice)
              ? "status"
              : "alert"
          }
        >
          {text[channel.notice]}
        </p>
        {channel.account && (
          <p>
            {channel.account.account_id} · {text.role}:{" "}
            {stateLabel(channel.account.role, text)} ·{" "}
            {channel.account.assurance} · {text.expires}:{" "}
            <time dateTime={channel.account.expires_at}>
              {channel.account.expires_at}
            </time>
          </p>
        )}
        <button disabled={channel.busy} onClick={() => void channel.run()}>
          {text.check}
        </button>
      </section>
      {channel.pending && (
        <section aria-label={text.pending}>
          <p>
            {text.pending}: <code>{channel.pending.command.key}</code>
          </p>
          <p>{text.unknown}</p>
          <button
            disabled={channel.busy || !channel.account}
            onClick={channel.retry}
          >
            {text.retry}
          </button>
        </section>
      )}
      {receipt && (
        <section aria-label={text.receipt}>
          <p>
            {text.receipt}:{" "}
            {receipt.state === "committed"
              ? text.committed
              : text.receiptPending}
          </p>
          <p>
            <code>{receipt.operation_id}</code>
          </p>
          {receipt.resource_id && (
            <p>
              <code>{receipt.resource_id}</code>
            </p>
          )}
        </section>
      )}
      {supported && (
        <div key={channel.epoch}>
          {role !== "governance" && (
            <TargetPanel
              channel={channel}
              text={text}
              onProposal={(value) => {
                setReceipt(value);
                if (value.resource_id) setProposalId(value.resource_id);
              }}
            />
          )}
          <PromotionPanel
            channel={channel}
            text={text}
            proposalId={proposalId}
            onProposalId={setProposalId}
            onReceipt={setReceipt}
          />
        </div>
      )}
      {channel.account && !supported && <p>{text.unsupported}</p>}
    </main>
  );
}
