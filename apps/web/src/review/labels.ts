import { manualMessages } from "../manual/messages";
import type { Locale } from "./types";
const en = {
  title: "Manual support review",
  help: "Open separate help",
  fallback: "Open independent fallback information",
  actor: "Signed-in actor",
  slot: "Review workspace",
  run: "Review run",
  signIn: "Sign in",
  signOut: "Sign out",
  language: "Language",
  retry: "Refresh workspace",
  loading: "Checking your workspace…",
  signedOut: "Sign in to this workspace. Your saved work will be recovered.",
  unavailable:
    "The service is unavailable. Saved work is preserved. Refresh to try again.",
  rejected:
    "This action could not be completed. Review the refreshed state before continuing.",
  authError:
    "Sign-in was interrupted or used the wrong account. Choose Sign in to restart safely.",
  wrongActor:
    "This account does not match the assigned review workspace. Sign out and use the account listed by the demo toolkit.",
  observer:
    "This tab is viewing the workspace. Another tab controls its actions.",
  claim: "Use this tab",
  connecting: "Connecting this tab…",
  closed: "This review run is closed. No new changes can be made.",
  saved: "Draft saved",
  saving: "Saving draft…",
  unsaved: "Draft not yet saved",
  draftError: "Draft could not be saved. Keep this tab open and retry.",
  pending:
    "A saved operation needs reconciliation. No new send will be created.",
  reconcile: "Check saved operation",
  resend: "Retry saved operation",
  cancel: "Discard prepared action",
  returnWorkspace: "Return to workspace",
  retryDraft: "Retry saving draft",
  operation: "Operation",
  choose: "Open a conversation",
  selected: "Current conversation",
  acknowledged: "Disclosure acknowledged",
  submitted: "Fictional situation submitted",
  waitOther: "Waiting for the other party to confirm.",
  expired:
    "Confirmation expired. The assigned worker can prepare a new confirmation.",
  expires: "Confirmation expires in",
  seconds: "seconds",
  ownAck: "Your app channel is confirmed.",
  interrupt:
    "I explicitly intend to interrupt and take responsibility as supervisor.",
  observed:
    "Observation granted for five minutes. No ownership change is implied.",
};
const fr: typeof en = {
  title: "Revue du soutien manuel",
  help: "Ouvrir l’aide séparée",
  fallback: "Ouvrir les renseignements de secours indépendants",
  actor: "Compte connecté",
  slot: "Espace de revue",
  run: "Séance de revue",
  signIn: "Se connecter",
  signOut: "Se déconnecter",
  language: "Langue",
  retry: "Actualiser l’espace",
  loading: "Vérification de votre espace…",
  signedOut:
    "Connectez-vous à cet espace. Votre travail enregistré sera récupéré.",
  unavailable:
    "Le service est indisponible. Le travail enregistré est conservé. Actualisez pour réessayer.",
  rejected:
    "Cette action n’a pas abouti. Vérifiez l’état actualisé avant de continuer.",
  authError:
    "La connexion a été interrompue ou le compte était incorrect. Choisissez Se connecter pour recommencer.",
  wrongActor:
    "Ce compte ne correspond pas à cet espace. Déconnectez-vous et utilisez le compte indiqué par l’outil de démonstration.",
  observer:
    "Cet onglet affiche l’espace. Un autre onglet contrôle les actions.",
  claim: "Utiliser cet onglet",
  connecting: "Connexion de cet onglet…",
  closed:
    "Cette séance de revue est fermée. Aucun nouveau changement n’est possible.",
  saved: "Brouillon enregistré",
  saving: "Enregistrement du brouillon…",
  unsaved: "Brouillon pas encore enregistré",
  draftError:
    "Le brouillon n’a pas été enregistré. Gardez cet onglet ouvert et réessayez.",
  pending:
    "Une opération enregistrée doit être vérifiée. Aucun nouvel envoi ne sera créé.",
  reconcile: "Vérifier l’opération enregistrée",
  resend: "Réessayer l’opération enregistrée",
  cancel: "Annuler l’action préparée",
  returnWorkspace: "Revenir à l’espace",
  retryDraft: "Réessayer l’enregistrement du brouillon",
  operation: "Opération",
  choose: "Ouvrir une conversation",
  selected: "Conversation actuelle",
  acknowledged: "Avis reconnu",
  submitted: "Situation fictive soumise",
  waitOther: "En attente de confirmation de l’autre personne.",
  expired:
    "La confirmation a expiré. L’intervenant affecté peut en préparer une nouvelle.",
  expires: "La confirmation expire dans",
  seconds: "secondes",
  ownAck: "Votre canal de l’application est confirmé.",
  interrupt:
    "Je souhaite explicitement interrompre et devenir responsable comme superviseur.",
  observed:
    "Observation accordée pour cinq minutes. Cela ne change pas le responsable.",
};
export function labels(locale: Locale) {
  return { ...manualMessages[locale], ...(locale === "fr-CA" ? fr : en) };
}
export type Labels = ReturnType<typeof labels>;
