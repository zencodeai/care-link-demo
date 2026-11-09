export const trustMessages = {
  "en-CA": {
    openHelp: "Open independent private help",
    title: "Private sign-in and human help",
    scope:
      "IMP-02 engineering candidate. Participant admission remains disabled. Use issued test accounts and fictional information only.",
    account: "Main account",
    helpAccount: "Separate private-help account",
    check: "Check sign-in",
    signIn: "Sign in",
    signOut: "Sign out",
    role: "Requested sign-in role",
    pid: "Participant",
    worker: "Worker",
    supervisor: "Supervisor",
    roleHint:
      "The identity service checks separately provisioned roles. Choosing a role does not grant it.",
    unchecked: "Sign-in has not been checked.",
    checking: "Checking current authority…",
    unavailable:
      "Current authority is unavailable. Private actions are disabled.",
    signed_out: "Sign in again to establish current authority.",
    rejected:
      "The service rejected this action. Check current access, request settings and revision before retrying.",
    invalid:
      "The service returned an incompatible result. Private actions are disabled.",
    unknown:
      "No confirmed result was received. Retry the same action to reconcile it; do not assume it failed.",
    busy: "Request pending…",
    active: "Current server role",
    assurance: "Assurance",
    expires: "Session expires",
    helpUnconfigured: "A separate HTTPS private-help origin is not configured.",
    oidcUnconfigured:
      "The approved identity-provider origin is not configured. Sign-in redirects are disabled.",
    request: "Opaque help request",
    privacy:
      "This request carries only language and an optional fictional jurisdiction. Do not enter names, needs, phone numbers or a story.",
    retrySettings:
      "If an earlier request has no confirmed result, restore its original language and fictional jurisdiction before retrying. This screen sends no jurisdiction. Changed settings are rejected to preserve the same request; do not start a replacement request.",
    create: "Request human help",
    helpId: "Help request ID",
    status: "Check help status",
    accept: "Accept request",
    cancel: "Cancel request",
    recorded: "Request recorded. A staffed connection is not confirmed.",
    accepted_unconnected:
      "A worker accepted this request. You are not connected.",
    cancelled: "Request cancelled.",
    reconciled: "Request reconciled. A staffed connection is not confirmed.",
    revision: "Current request revision",
    noHelp: "No current help result is displayed.",
    stepUp: "Fresh verification",
    purpose: "Verification purpose",
    resource: "Resource ID",
    startStep: "Start verification",
    confirmStep: "Confirm verification",
    proof: "Completed verification intent ID",
    ceremony: "Verification state",
    notBefore: "Earliest confirmation",
    export: "Export",
    delete: "Delete",
    plan_view: "View plan",
    stepHint:
      "Verification does not perform the selected operation. Export and deletion require cooling-off and another fresh MFA proof.",
    fallbackUnconfigured: "The independent fallback origin is not configured.",
    fallback: "Independent fallback information",
    fallbackHint:
      "The fallback page reports its own content-review status. Private help is unavailable when identity authority is lost.",
    invalidId: "Enter a valid request or resource UUID.",
  },
  "fr-CA": {
    openHelp: "Ouvrir l’aide privée indépendante",
    title: "Connexion privée et aide humaine",
    scope:
      "Candidat technique IMP-02. L’admission des participants reste désactivée. Utilisez uniquement des comptes de test attribués et des données fictives.",
    account: "Compte principal",
    helpAccount: "Compte distinct pour l’aide privée",
    check: "Vérifier la connexion",
    signIn: "Se connecter",
    signOut: "Se déconnecter",
    role: "Rôle de connexion demandé",
    pid: "Participant",
    worker: "Intervenant",
    supervisor: "Superviseur",
    roleHint:
      "Le service d’identité vérifie les rôles attribués séparément. Choisir un rôle ne l’accorde pas.",
    unchecked: "La connexion n’a pas été vérifiée.",
    checking: "Vérification de l’autorité actuelle…",
    unavailable:
      "L’autorité actuelle est indisponible. Les actions privées sont désactivées.",
    signed_out: "Reconnectez-vous pour établir l’autorité actuelle.",
    rejected:
      "Le service a refusé cette action. Vérifiez l’accès, les paramètres de la demande et la révision avant de réessayer.",
    invalid:
      "Le service a renvoyé un résultat incompatible. Les actions privées sont désactivées.",
    unknown:
      "Aucun résultat confirmé n’a été reçu. Réessayez la même action pour la rapprocher; ne supposez pas qu’elle a échoué.",
    busy: "Demande en attente…",
    active: "Rôle actuel selon le serveur",
    assurance: "Niveau d’assurance",
    expires: "Expiration de session",
    helpUnconfigured:
      "L’origine HTTPS distincte de l’aide privée n’est pas configurée.",
    oidcUnconfigured:
      "L’origine approuvée du fournisseur d’identité n’est pas configurée. Les redirections de connexion sont désactivées.",
    request: "Demande d’aide opaque",
    privacy:
      "Cette demande contient uniquement la langue et une juridiction fictive facultative. N’entrez aucun nom, besoin, numéro de téléphone ou récit.",
    retrySettings:
      "Si une demande précédente n’a aucun résultat confirmé, rétablissez sa langue et sa juridiction fictive d’origine avant de réessayer. Cet écran n’envoie aucune juridiction. Les paramètres modifiés sont refusés pour conserver la même demande; ne créez pas une demande de remplacement.",
    create: "Demander une aide humaine",
    helpId: "Identifiant de demande d’aide",
    status: "Vérifier l’état de l’aide",
    accept: "Accepter la demande",
    cancel: "Annuler la demande",
    recorded:
      "Demande enregistrée. Aucune connexion avec un intervenant n’est confirmée.",
    accepted_unconnected:
      "Un intervenant a accepté cette demande. Vous n’êtes pas connecté.",
    cancelled: "Demande annulée.",
    reconciled:
      "Demande rapprochée. Aucune connexion avec un intervenant n’est confirmée.",
    revision: "Révision actuelle de la demande",
    noHelp: "Aucun résultat d’aide actuel n’est affiché.",
    stepUp: "Vérification récente",
    purpose: "Objet de la vérification",
    resource: "Identifiant de la ressource",
    startStep: "Commencer la vérification",
    confirmStep: "Confirmer la vérification",
    proof: "Identifiant de l’intention de vérification terminée",
    ceremony: "État de la vérification",
    notBefore: "Première confirmation possible",
    export: "Exportation",
    delete: "Suppression",
    plan_view: "Consulter le plan",
    stepHint:
      "La vérification n’exécute pas l’opération choisie. L’exportation et la suppression nécessitent un délai de réflexion et une nouvelle preuve MFA récente.",
    fallbackUnconfigured:
      "L’origine du repli indépendant n’est pas configurée.",
    fallback: "Information de repli indépendante",
    fallbackHint:
      "La page de repli indique son propre état de révision du contenu. L’aide privée est indisponible si l’autorité d’identité est perdue.",
    invalidId: "Entrez un UUID valide pour la demande ou la ressource.",
  },
} as const;

export type Locale = keyof typeof trustMessages;
export type Text = (typeof trustMessages)[Locale];
