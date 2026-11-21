const en = {
  loadRightsScope:
    "Open your current service session above to load the scope for a new request. Refresh that session if your permissions change.",
  outcomeSaved: "Outcome recorded. Refresh outcomes to read current records.",
  exceptionReasons: {
    backup: "Backup deletion is pending.",
    physical: "Physical storage erasure has not been proven.",
    otherAuthor: "Other authors’ private content was excluded.",
    retained: "Some active copies remain retained.",
    held: "An authorized hold retains dependent content.",
    dependency: "A copy dependency needs review before deletion.",
    anchor: "An explicit retention event is still required.",
    notDue: "The retention period has not ended.",
    unclassified: "The copy classification requires review.",
    unknown: "A retained exception requires authorized review.",
  },
  contactTitle: "Contact permission",
  contactHint:
    "A separate MFA verification authorizes creating a contact grant for this subject. Review the recipient, fields and expiry before confirming.",
  contactVerify: "Verify contact permission",
  contactExpiry: "Contact permission expiry",
  previewContact: "Review contact permission",
  confirmContact: "Confirm this contact permission",
  revokeContact: "Withdraw contact permission",
  contactFields: "Permitted contact fields: summary and outcome",
  contactWithdrawn:
    "Contact permission withdrawn. Follow-up not yet authorized cannot be delivered.",
  title: "Follow-up and my data",
  language: "Language",
  scope:
    "Private synthetic demonstration. Follow-up stays in your CARE-Link inbox.",
  account: "Current account",
  check: "Check my account",
  signIn: "Sign in and manage my account",
  busy: "Checking current permission…",
  ready: "Current account checked.",
  unchecked: "Check your account before opening private information.",
  unavailable: "The service is unavailable. Try again.",
  signed_out: "Sign in again to continue.",
  rejected:
    "This action was declined. Refresh the current record before trying again.",
  invalid: "The request or reply could not be verified.",
  unknown:
    "The result is unknown. Keep this request and retry it with its original reference.",
  pending: "Unconfirmed request",
  retry: "Retry the same request",
  session: "Service session reference",
  load: "Open session",
  revision: "Current revision",
  subject: "Own subject reference",
  reference: "Reference",
  refresh: "Refresh",
  due: "Follow-up time",
  anchor: "Explicit post-crisis event",
  anchorHint:
    "Record the event you observed. No event is inferred from silence or connection.",
  occurred: "When the event occurred",
  sourceEvent: "Source event reference",
  recordAnchor: "Record post-crisis event",
  followup: "Follow-up",
  grant: "Separate contact permission reference",
  recipient: "Internal recipient account reference",
  pendingAnchor: "Keep pending until an event is recorded",
  schedule: "Request follow-up",
  bind: "Bind recorded event",
  window:
    "Choose a time 24–72 hours after the recorded event. Separate, current contact permission must name the subject, recipient and purpose.",
  consentLink: "Review contact permission",
  cancel: "Cancel follow-up",
  cancellation:
    "Cancellation before delivery authorization stops delivery. Once authorized, cancellation may be too late.",
  unknownDelivery:
    "Delivery needs reconciliation. A timeout does not prove that no message was delivered.",
  inbox: "My inbox",
  openInbox: "Refresh my inbox",
  noMessages: "No current inbox messages.",
  openMessage: "Open message",
  next: "Next page",
  expires: "Expires",
  readAt: "Read",
  outcomes: "Attributed outcomes",
  outcomeHint:
    "Record only an observed or reported outcome. Receiving a message does not establish a connection or benefit.",
  outcomeState: "Observed outcome",
  carer: "Carer support outcome",
  observed: "Observation time",
  appendOutcome: "Record outcome",
  readOutcomes: "Refresh outcomes",
  noOutcomes: "No outcomes recorded.",
  rights: "Export or delete my data",
  rightsScope:
    "Only your own permitted content is included. Mentioning another person does not authorize access to that person's reports.",
  kind: "Request",
  export: "Export",
  delete: "Delete",
  rightsRevision: "Current subject revision",
  verification: "Verify my authority",
  verificationHint:
    "Export and deletion require MFA, a five-minute cooling period, then a second fresh MFA sign-in for this exact request.",
  begin: "Begin MFA verification",
  second: "Start fresh MFA after cooling",
  confirm: "Confirm completed MFA sign-in",
  cooling: "Cooling period ends",
  verified: "Authority verified for this purpose and subject.",
  providerMissing: "Secure sign-in is not configured for this browser.",
  popupBlocked: "Allow the secure sign-in window, then try again.",
  submitRights: "Submit my request",
  deleteConfirm: "I request deletion of my eligible active content.",
  deletionHint:
    "Eligible active deletion has a 24-hour target. Backup expiry has a seven-day target. Neither target proves completion or physical erasure.",
  progress: "Request progress",
  deadline: "Target deadline",
  exceptions: "Retained exceptions",
  noExceptions: "No exceptions reported.",
  backup:
    "Backup deletion remains pending. Active-content deletion does not prove physical erasure from storage or backups.",
  download: "Open my authorized export once",
  exportHint:
    "The encrypted export expires after 15 minutes. Opening it requires current permission and fresh verification; the one-use download cannot be repeated.",
  exportData: "Authorized export",
  assertions: "Own reports",
  plans: "Permitted plans",
  outcomeRefs: "Outcome references",
  hold: "Retention holds",
  holdHint:
    "A hold can retain dependent content. Releasing it requires separately authorized review; it does not immediately delete content.",
  knownRights: "Existing rights request reference",
  knownFollowup: "Existing follow-up reference",
  state: "Status",
  ownSubject:
    "Use your own subject reference. Carers cannot request another person's data.",
  currentSession: "Opened service session",
  reviewLater:
    "Human usability, language and screen-reader review is deferred until after implementation slice 10.",
  states: {
    anchor_pending: "Waiting for a recorded event",
    scheduled: "Scheduled",
    claimed: "Processing",
    authorized: "Delivery authorized; cancellation may be too late",
    sent: "Delivered to internal inbox",
    cancelled: "Cancelled before delivery",
    expired: "Expired",
    unknown: "Unknown",
    reconciliation_needed: "Reconciliation required",
    requested: "Requested",
    eligible: "Eligible",
    held: "Held for review",
    active_purged: "Eligible active content purged",
    backup_pending: "Backup deletion pending",
    completed: "Completed within the stated scope",
    completed_with_exceptions: "Completed with retained exceptions",
    failed: "Failed",
    offered: "Offered",
    chosen: "Chosen",
    declined: "Declined",
    attempted: "Attempted",
    received: "Received",
    accepted: "Accepted",
    connected: "Connection observed",
    reported_benefit: "Benefit reported",
  },
};
export type Text = typeof en;
const fr: Text = {
  loadRightsScope:
    "Ouvrez votre séance de service actuelle ci-dessus pour charger la portée d’une nouvelle demande. Actualisez cette séance si vos autorisations changent.",
  outcomeSaved:
    "Résultat consigné. Actualisez les résultats pour lire les dossiers actuels.",
  exceptionReasons: {
    backup: "La suppression des sauvegardes est en attente.",
    physical: "L’effacement physique du stockage n’a pas été prouvé.",
    otherAuthor: "Le contenu privé des autres auteurs a été exclu.",
    retained: "Certaines copies actives restent conservées.",
    held: "Une suspension autorisée conserve du contenu dépendant.",
    dependency: "Une dépendance de copie exige un examen avant la suppression.",
    anchor: "Un événement explicite de conservation est encore requis.",
    notDue: "La période de conservation n’est pas terminée.",
    unclassified: "La classification de la copie exige un examen.",
    unknown: "Une exception de conservation exige un examen autorisé.",
  },
  contactTitle: "Consentement au contact",
  contactHint:
    "Une vérification multifacteur distincte autorise la création du consentement pour cette personne. Examinez le destinataire, les champs et l’expiration avant de confirmer.",
  contactVerify: "Vérifier le consentement au contact",
  contactExpiry: "Expiration du consentement au contact",
  previewContact: "Examiner le consentement au contact",
  confirmContact: "Confirmer ce consentement au contact",
  revokeContact: "Retirer le consentement au contact",
  contactFields: "Champs autorisés pour le contact : résumé et résultat",
  contactWithdrawn:
    "Consentement au contact retiré. Un suivi non encore autorisé ne peut pas être livré.",
  title: "Suivi et mes données",
  language: "Langue",
  scope:
    "Démonstration synthétique privée. Le suivi reste dans votre boîte CARE-Link.",
  account: "Compte actuel",
  check: "Vérifier mon compte",
  signIn: "Se connecter et gérer mon compte",
  busy: "Vérification des autorisations actuelles…",
  ready: "Compte actuel vérifié.",
  unchecked: "Vérifiez votre compte avant d'ouvrir des renseignements privés.",
  unavailable: "Le service est indisponible. Réessayez.",
  signed_out: "Reconnectez-vous pour continuer.",
  rejected:
    "Cette action a été refusée. Actualisez le dossier avant de réessayer.",
  invalid: "La demande ou la réponse n'a pas pu être vérifiée.",
  unknown:
    "Le résultat est inconnu. Conservez cette demande et réessayez avec sa référence originale.",
  pending: "Demande non confirmée",
  retry: "Réessayer la même demande",
  session: "Référence de la séance de service",
  load: "Ouvrir la séance",
  revision: "Version actuelle",
  subject: "Votre référence de personne",
  reference: "Référence",
  refresh: "Actualiser",
  due: "Heure du suivi",
  anchor: "Événement explicite après la crise",
  anchorHint:
    "Consignez l'événement observé. Aucun événement n'est déduit du silence ou de la connexion.",
  occurred: "Moment de l'événement",
  sourceEvent: "Référence de l'événement source",
  recordAnchor: "Consigner l'événement après la crise",
  followup: "Suivi",
  grant: "Référence du consentement distinct au contact",
  recipient: "Référence du compte destinataire interne",
  pendingAnchor: "Laisser en attente d'un événement consigné",
  schedule: "Demander un suivi",
  bind: "Associer l'événement consigné",
  window:
    "Choisissez une heure de 24 à 72 heures après l'événement consigné. Le consentement actuel et distinct au contact doit préciser la personne, le destinataire et le but.",
  consentLink: "Examiner le consentement au contact",
  cancel: "Annuler le suivi",
  cancellation:
    "L'annulation avant l'autorisation de livraison empêche la livraison. Après l'autorisation, il peut être trop tard.",
  unknownDelivery:
    "La livraison exige un rapprochement. Un délai dépassé ne prouve pas l'absence de livraison.",
  inbox: "Ma boîte de réception",
  openInbox: "Actualiser ma boîte",
  noMessages: "Aucun message actuel dans la boîte.",
  openMessage: "Ouvrir le message",
  next: "Page suivante",
  expires: "Expiration",
  readAt: "Lu",
  outcomes: "Résultats attribués",
  outcomeHint:
    "Consignez seulement un résultat observé ou rapporté. La réception d'un message ne prouve ni une connexion ni un bénéfice.",
  outcomeState: "Résultat observé",
  carer: "Résultat du soutien à la personne aidante",
  observed: "Heure de l'observation",
  appendOutcome: "Consigner le résultat",
  readOutcomes: "Actualiser les résultats",
  noOutcomes: "Aucun résultat consigné.",
  rights: "Exporter ou supprimer mes données",
  rightsScope:
    "Seul votre propre contenu autorisé est inclus. Mentionner une autre personne n'autorise pas l'accès à ses rapports.",
  kind: "Demande",
  export: "Exporter",
  delete: "Supprimer",
  rightsRevision: "Version actuelle de la personne",
  verification: "Vérifier mon autorité",
  verificationHint:
    "L'exportation et la suppression exigent une authentification multifacteur, cinq minutes d'attente, puis une seconde authentification récente pour cette demande exacte.",
  begin: "Commencer la vérification multifacteur",
  second: "Nouvelle authentification après l'attente",
  confirm: "Confirmer l'authentification terminée",
  cooling: "Fin du délai d'attente",
  verified: "Autorité vérifiée pour ce but et cette personne.",
  providerMissing:
    "La connexion sécurisée n'est pas configurée dans ce navigateur.",
  popupBlocked: "Autorisez la fenêtre de connexion sécurisée, puis réessayez.",
  submitRights: "Envoyer ma demande",
  deleteConfirm: "Je demande la suppression de mon contenu actif admissible.",
  deletionHint:
    "Le délai cible est de 24 heures pour le contenu actif admissible et de sept jours pour les sauvegardes. Ces cibles ne prouvent ni l'achèvement ni l'effacement physique.",
  progress: "Progression de la demande",
  deadline: "Échéance cible",
  exceptions: "Exceptions conservées",
  noExceptions: "Aucune exception signalée.",
  backup:
    "La suppression des sauvegardes reste en attente. La suppression du contenu actif ne prouve pas l'effacement physique du stockage ou des sauvegardes.",
  download: "Ouvrir une fois mon exportation autorisée",
  exportHint:
    "L'exportation chiffrée expire après 15 minutes. Son ouverture exige une autorisation actuelle et une vérification récente; le téléchargement est à usage unique.",
  exportData: "Exportation autorisée",
  assertions: "Mes rapports",
  plans: "Plans autorisés",
  outcomeRefs: "Références des résultats",
  hold: "Suspensions de conservation",
  holdHint:
    "Une suspension peut conserver du contenu dépendant. Sa levée exige un examen autorisé distinct; elle ne supprime pas immédiatement le contenu.",
  knownRights: "Référence d'une demande de droits existante",
  knownFollowup: "Référence d'un suivi existant",
  state: "État",
  ownSubject:
    "Utilisez votre propre référence. Une personne aidante ne peut pas demander les données d'une autre personne.",
  currentSession: "Séance de service ouverte",
  reviewLater:
    "L'examen humain de l'utilisabilité, de la langue et du lecteur d'écran est reporté après la tranche 10.",
  states: {
    anchor_pending: "En attente d'un événement consigné",
    scheduled: "Prévu",
    claimed: "En traitement",
    authorized: "Livraison autorisée; l'annulation peut être trop tardive",
    sent: "Livré dans la boîte interne",
    cancelled: "Annulé avant la livraison",
    expired: "Expiré",
    unknown: "Inconnu",
    reconciliation_needed: "Rapprochement nécessaire",
    requested: "Demandé",
    eligible: "Admissible",
    held: "Suspendu pour examen",
    active_purged: "Contenu actif admissible supprimé",
    backup_pending: "Suppression des sauvegardes en attente",
    completed: "Terminé dans la portée indiquée",
    completed_with_exceptions: "Terminé avec des exceptions conservées",
    failed: "Échec",
    offered: "Offert",
    chosen: "Choisi",
    declined: "Refusé",
    attempted: "Tenté",
    received: "Reçu",
    accepted: "Accepté",
    connected: "Connexion observée",
    reported_benefit: "Bénéfice rapporté",
  },
};
export const messages = { "en-CA": en, "fr-CA": fr };

export function exceptionLabel(code: string, text: Text): string {
  if (code === "backup_erasure_pending_IMP09")
    return text.exceptionReasons.backup;
  if (code === "physical_erasure_not_proven")
    return text.exceptionReasons.physical;
  if (code === "other_author_private_content_excluded")
    return text.exceptionReasons.otherAuthor;
  if (code.startsWith("retained_active_copies:"))
    return text.exceptionReasons.retained;
  if (code === "active_hold") return text.exceptionReasons.held;
  if (["unknown_dependency", "cyclic_dependency"].includes(code))
    return text.exceptionReasons.dependency;
  if (["anchor_pending", "parent_anchor_pending"].includes(code))
    return text.exceptionReasons.anchor;
  if (code === "not_due") return text.exceptionReasons.notDue;
  if (code === "unclassified_copy") return text.exceptionReasons.unclassified;
  return text.exceptionReasons.unknown;
}
