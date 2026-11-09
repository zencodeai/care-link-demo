import { configuredOrigin } from "./api";
import { useChannel } from "./channel";
import { HelpTools } from "./HelpTools";
import { AccountPanel, Verification } from "./IdentityPanel";
import { trustMessages, type Locale } from "./messages";
export function TrustAndHelp({
  locale,
  helpOrigin = null,
  oidcOrigin = null,
  staticOrigin = null,
  surface = "main",
  navigate = (url: string) => window.location.assign(url),
}: {
  locale: Locale;
  helpOrigin?: string | null;
  oidcOrigin?: string | null;
  staticOrigin?: string | null;
  surface?: "main" | "help";
  navigate?: (url: string) => void;
}) {
  const text = trustMessages[locale];
  const main = useChannel("");
  const help = useChannel("");
  const approvedOidc = configuredOrigin(oidcOrigin ?? undefined);
  const approvedHelp = configuredOrigin(helpOrigin ?? undefined);
  const staticCandidate = configuredOrigin(staticOrigin ?? undefined);
  const approvedStatic =
    staticCandidate !== window.location.origin &&
    staticCandidate !== approvedHelp
      ? staticCandidate
      : null;
  return (
    <section aria-labelledby="trust-title">
      <h2 id="trust-title">{text.title}</h2>
      <p className="notice">{text.scope}</p>
      {surface === "main" && (
        <AccountPanel
          channel={main}
          text={text}
          locale={locale}
          id="main-account"
          title={text.account}
          oidcOrigin={approvedOidc}
          navigate={navigate}
        >
          <Verification
            channel={main}
            text={text}
            oidcOrigin={approvedOidc}
            navigate={navigate}
          />
        </AccountPanel>
      )}
      {surface === "help" ? (
        <AccountPanel
          channel={help}
          text={text}
          locale={locale}
          id="help-account"
          title={text.helpAccount}
          oidcOrigin={approvedOidc}
          navigate={navigate}
        >
          <HelpTools channel={help} text={text} locale={locale} />
        </AccountPanel>
      ) : approvedHelp && approvedHelp !== window.location.origin ? (
        <p>
          <a href={`${approvedHelp}/private-help`}>{text.openHelp}</a>
        </p>
      ) : (
        <p>{text.helpUnconfigured}</p>
      )}
      {approvedStatic ? (
        <p>
          <a href={`${approvedStatic}/fallback?locale=${locale}`}>
            {text.fallback}
          </a>
        </p>
      ) : (
        <p>{text.fallbackUnconfigured}</p>
      )}
      <p className="hint">{text.fallbackHint}</p>
    </section>
  );
}
