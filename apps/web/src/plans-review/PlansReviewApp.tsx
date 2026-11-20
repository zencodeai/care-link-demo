import { useEffect, useState } from "react";
import { PlansWorkspace } from "../plans/PlansWorkspace";
import type { Locale } from "../plans/api";
import type { PlansReviewActions } from "../plans/review";
import { usePlansReview, type PlansReviewChannel } from "./usePlansReview";
import { usePlanDraft } from "./usePlanDraft";

const labels = {
  "en-CA": {
    title: "Plans and sharing review",
    synthetic: "Synthetic review · automatic review sign-in",
    language: "Language",
    expiry: "Review ends",
    loading: "Connecting and checking your current access…",
    renewing: "Restoring your review session. Your unsent words remain here.",
    observer:
      "This review is open in another page. Continue here to take control.",
    expired: "This review has ended. Ask the reviewer to start a new run.",
    rejected:
      "Current access could not be confirmed. Protected information is hidden.",
    unavailable:
      "The review connection is unavailable. Your unsent words remain here.",
    ready: "Your review is ready.",
    claim: "Continue here",
    retry: "Reconnect",
    diagnostics: "Review details",
    saved: "Draft saved",
    saving: "Saving draft…",
    unsaved: "Draft has unsaved changes",
    draftError:
      "Draft could not be saved. Keep this page open and reconnect before saving again.",
    save: "Save draft",
    pid: "Person reviewing their plan",
    carer: "Carer",
    professional_participant: "Professional participant",
    worker: "Service worker",
  },
  "fr-CA": {
    title: "Examen du plan et du partage",
    synthetic: "Examen synthétique · connexion automatique",
    language: "Langue",
    expiry: "Fin de l’examen",
    loading: "Connexion et vérification de votre accès actuel…",
    renewing:
      "Rétablissement de votre session. Vos mots non envoyés restent ici.",
    observer:
      "Cet examen est ouvert dans une autre page. Continuez ici pour prendre le contrôle.",
    expired:
      "Cet examen est terminé. Demandez un nouvel examen à la personne responsable.",
    rejected:
      "Votre accès actuel n’a pas pu être confirmé. Les renseignements protégés sont masqués.",
    unavailable:
      "La connexion à l’examen est indisponible. Vos mots non envoyés restent ici.",
    ready: "Votre examen est prêt.",
    claim: "Continuer ici",
    retry: "Reconnecter",
    diagnostics: "Détails de l’examen",
    saved: "Brouillon enregistré",
    saving: "Enregistrement du brouillon…",
    unsaved: "Le brouillon comporte des modifications non enregistrées",
    draftError:
      "Impossible d’enregistrer le brouillon. Gardez cette page ouverte et reconnectez-vous avant de réessayer.",
    save: "Enregistrer le brouillon",
    pid: "Personne examinant son plan",
    carer: "Personne proche aidante",
    professional_participant: "Participant professionnel",
    worker: "Intervenant",
  },
};
function ReviewBody({
  channel,
  locale,
}: {
  channel: PlansReviewChannel;
  locale: Locale;
}) {
  const draft = usePlanDraft(channel),
    ctx = channel.context!,
    workspace = channel.workspace!;
  const review: PlansReviewActions = {
    account_id: ctx.account_id,
    role: ctx.role,
    expires_at: ctx.expires_at,
    enabled: channel.enabled && !draft.invalid,
    renew: channel.renew,
    enter: channel.enter,
    verify: async (subject, revision, signal, work) => {
      await draft.flush(signal, work);
      return channel.verify(subject, revision, signal, work);
    },
  };
  const text = labels[locale];
  return (
    <>
      {draft.invalid && (
        <button
          type="button"
          disabled={!channel.enabled}
          onClick={draft.resetInvalid}
        >
          {locale === "fr-CA"
            ? "Continuer avec les mots de cette page"
            : "Continue with the words on this page"}
        </button>
      )}
      <p role={draft.state === "draftError" ? "alert" : "status"}>
        {text[draft.state]}
      </p>
      <button
        type="button"
        disabled={!channel.enabled || draft.invalid || draft.state === "saving"}
        onClick={() => {
          void draft.flush().catch(() => {});
        }}
      >
        {text.save}
      </button>
      <PlansWorkspace
        locale={locale}
        viewId={channel.view?.view_id ?? null}
        review={review}
        draft={draft.bridge}
        selection={workspace.selection}
        resumption={channel.resumption}
      />
    </>
  );
}
export function PlansReviewApp() {
  const channel = usePlansReview();
  const [locale, setLocale] = useState<Locale>(() =>
    new URL(window.location.href).searchParams.get("locale") === "fr-CA"
      ? "fr-CA"
      : "en-CA",
  );
  const text = labels[locale],
    ctx = channel.context;
  useEffect(() => {
    document.documentElement.lang = locale;
    document.title = text.title;
  }, [locale, text.title]);
  return (
    <main>
      <header>
        <h1>{text.title}</h1>
        <p>{text.synthetic}</p>
        <label htmlFor="review-language">{text.language}</label>
        <select
          id="review-language"
          value={locale}
          onChange={(event) => {
            const next = event.target.value === "fr-CA" ? "fr-CA" : "en-CA";
            const destination = new URL(window.location.href);
            destination.searchParams.set("locale", next);
            window.history.replaceState(null, "", destination);
            setLocale(next);
          }}
        >
          <option value="en-CA">English</option>
          <option value="fr-CA">Français</option>
        </select>
        {ctx && (
          <>
            <p>
              {text[
                ctx.role as
                  | "pid"
                  | "carer"
                  | "professional_participant"
                  | "worker"
              ] ?? ctx.role}
            </p>
            <p>
              {text.expiry}:{" "}
              <time dateTime={ctx.expires_at}>
                {new Date(ctx.expires_at).toLocaleString(locale)}
              </time>
            </p>
          </>
        )}
      </header>
      <p
        role={
          channel.status === "rejected" || channel.status === "unavailable"
            ? "alert"
            : "status"
        }
      >
        {text[channel.status]}
      </p>
      {channel.status === "observer" ? (
        <button
          type="button"
          onClick={() => {
            void channel.claim();
          }}
        >
          {text.claim}
        </button>
      ) : (
        ["rejected", "unavailable"].includes(channel.status) && (
          <button
            type="button"
            onClick={() => {
              void channel.refresh();
            }}
          >
            {text.retry}
          </button>
        )
      )}
      {ctx && channel.workspace && (
        <ReviewBody
          key={[
            ctx.run_id,
            ctx.slot_id,
            ctx.account_id,
            ctx.role,
            channel.workspace.selection.session_id,
          ].join(":")}
          channel={channel}
          locale={locale}
        />
      )}
      {ctx && (
        <details>
          <summary>{text.diagnostics}</summary>
          <p>
            {ctx.run_id} · {ctx.slot_id} · {ctx.account_id}
          </p>
          <p>
            {channel.workspace?.selection.session_id} ·{" "}
            {channel.workspace?.selection.plan_id}
          </p>
        </details>
      )}
    </main>
  );
}
