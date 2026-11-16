export type Locale = "en-CA" | "fr-CA";
const en = {
  title: "Manual support",
  scope:
    "Private fictional practice only. AI is unavailable; a person can still provide manual support. Do not enter real personal information.",
  recoveryUnproven:
    "Conversation recovery has not been qualified for this demonstration.",
  check: "Check manual access",
  unchecked: "Sign in above, then check your current access.",
  checking: "Checking current access…",
  unavailable:
    "Current access or service is unavailable. Private information is hidden; unsent text is preserved.",
  signed_out:
    "Sign in again. Private information is hidden; unsent text is preserved.",
  rejected:
    "The action was rejected. Refresh current state before making another choice.",
  invalid:
    "The service returned an incompatible result. Private information is hidden.",
  pending: "Waiting for a durable acknowledgement…",
  committed: "The service acknowledged the operation.",
  unknown:
    "The result is unknown. Check this operation or retry the same action. Do not create another send.",
  operation: "Operation",
  retry: "Retry the same operation",
  reconcile: "Check operation status",
  resolved: "Current operation status",
  role: "Current signed-in role",
  participant: "Participant conversation",
  worker: "Worker workspace",
  supervisor: "Supervisor workspace",
  unsupported:
    "This signed-in role has no manual workspace. Sign in with a participant, worker or supervisor role.",
  create: "Start a fictional conversation",
  session: "Conversation ID",
  open: "Open current conversation",
  refresh: "Refresh current state",
  phase: "Service state",
  owner: "Accountable owner",
  none: "No assigned human",
  epoch: "Control generation",
  unresolved: "Support remains unresolved.",
  ended:
    "You explicitly ended this conversation. Unresolved status remains recorded.",
  connected:
    "Both parties confirmed the app channel. Human support is connected.",
  unconnected: "A human connection has not been confirmed.",
  disconnected: "Channel disconnected. This does not end your support request.",
  disclosure: "Before fictional intake",
  acknowledge: "I understand this practice disclosure",
  disclosureMissing:
    "A current disclosure artifact is unavailable. Intake stays disabled; you can still request a human.",
  story: "Fictional situation",
  turn: "Submit fictional situation",
  human: "Ask for a human",
  end: "End my conversation",
  endConfirm:
    "I choose to end this conversation, even if support remains unresolved.",
  queue: "Current support queue",
  loadQueue: "Refresh queue",
  noQueue: "No visible queue entries.",
  waiting: "Waiting for assignment; no connection is implied.",
  eta: "Wait estimate is unknown.",
  reserve: "Reserve for myself",
  accept: "Accept reservation",
  prepare: "Prepare a new channel confirmation",
  accepted: "Assignment accepted. A connection still requires both parties.",
  challenge: "Confirm my app channel",
  oneParty:
    "Your channel was acknowledged. The other party must confirm independently.",
  twoParty:
    "Both app channels were acknowledged. The assigned worker must confirm the handoff.",
  confirm: "Confirm handoff",
  refreshAck: "Check the other party’s channel confirmation",
  confirmHint:
    "The worker confirms last so this page receives the combined channel evidence.",
  transferFailed: "Connection failed — requeue support",
  observe: "Observe for five minutes",
  prepareInterrupt: "Prepare interruption",
  interruptChoice:
    "I intend to interrupt this conversation as supervisor. Observation alone does not allow takeover.",
  confirmInterrupt: "Confirm interruption scope for five minutes",
  interruptReady:
    "Interruption scope was acknowledged. Refresh the conversation before takeover.",
  takeover: "Take over as accountable supervisor",
  takeoverHint:
    "Takeover fences the previous owner. A new app-channel confirmation is required before connected status.",
  message: "Manual message",
  send: "Send manual message",
  conversation: "Current authorized conversation",
  noMessages: "No visible messages.",
  more: "Older messages are available. Load the next page.",
  next: "Load older messages",
  author: "Author",
  source: "Attribution",
  invalidId: "Enter a complete conversation ID.",
  active: "Fictional intake active",
  human_requested: "Human help requested",
  queued: "Waiting in the support queue",
  worker_assigned: "Worker assigned — connection unconfirmed",
  handoff_pending: "Two-party connection confirmation pending",
  human_controlled: "Human owns the conversation",
  endedPhase: "Conversation ended by explicit choice",
} as const;
export type Text = { [K in keyof typeof en]: string };
const fr: Text = {
  title: "Soutien manuel",
  scope:
    "Exercice privé et fictif seulement. L’IA est indisponible; une personne peut offrir un soutien manuel. Ne saisissez aucune donnée personnelle réelle.",
  recoveryUnproven:
    "La récupération des conversations n’a pas été qualifiée pour cette démonstration.",
  check: "Vérifier mon accès au soutien",
  unchecked: "Connectez-vous ci-dessus, puis vérifiez votre accès actuel.",
  checking: "Vérification de l’accès actuel…",
  unavailable:
    "L’accès actuel ou le service est indisponible. Les données privées sont masquées; le texte non envoyé est conservé.",
  signed_out:
    "Reconnectez-vous. Les données privées sont masquées; le texte non envoyé est conservé.",
  rejected: "L’action a été refusée. Actualisez l’état avant un nouveau choix.",
  invalid:
    "La réponse du service est incompatible. Les données privées sont masquées.",
  pending: "En attente d’un accusé durable…",
  committed: "Le service a confirmé l’opération.",
  unknown:
    "Le résultat est inconnu. Vérifiez cette opération ou réessayez la même action. Ne créez pas un autre envoi.",
  operation: "Opération",
  retry: "Réessayer la même opération",
  reconcile: "Vérifier l’état de l’opération",
  resolved: "État actuel de l’opération",
  role: "Rôle de la session actuelle",
  participant: "Conversation du participant",
  worker: "Espace de l’intervenant",
  supervisor: "Espace du superviseur",
  unsupported:
    "Ce rôle n’a pas d’espace de soutien manuel. Connectez-vous comme participant, intervenant ou superviseur.",
  create: "Commencer une conversation fictive",
  session: "Identifiant de conversation",
  open: "Ouvrir la conversation actuelle",
  refresh: "Actualiser l’état",
  phase: "État du service",
  owner: "Responsable actuel",
  none: "Aucune personne affectée",
  epoch: "Génération de contrôle",
  unresolved: "Le besoin de soutien demeure non résolu.",
  ended:
    "Vous avez explicitement terminé cette conversation. L’état non résolu demeure enregistré.",
  connected:
    "Les deux personnes ont confirmé le canal de l’application. Le soutien humain est connecté.",
  unconnected: "Aucune connexion humaine n’a été confirmée.",
  disconnected:
    "Canal déconnecté. Cela ne termine pas votre demande de soutien.",
  disclosure: "Avant la saisie fictive",
  acknowledge: "Je comprends cet avis d’exercice",
  disclosureMissing:
    "L’avis actuel est indisponible. La saisie demeure désactivée; vous pouvez demander une personne.",
  story: "Situation fictive",
  turn: "Soumettre la situation fictive",
  human: "Demander une personne",
  end: "Terminer ma conversation",
  endConfirm:
    "Je choisis de terminer cette conversation, même si le soutien demeure non résolu.",
  queue: "File actuelle de soutien",
  loadQueue: "Actualiser la file",
  noQueue: "Aucune demande visible.",
  waiting: "En attente d’affectation; cela n’indique aucune connexion.",
  eta: "Le délai d’attente est inconnu.",
  reserve: "Réserver pour moi",
  accept: "Accepter la réservation",
  prepare: "Préparer une nouvelle confirmation du canal",
  accepted:
    "Affectation acceptée. Les deux personnes doivent encore confirmer la connexion.",
  challenge: "Confirmer mon canal de l’application",
  oneParty:
    "Votre canal est confirmé. L’autre personne doit confirmer séparément.",
  twoParty:
    "Les deux canaux sont confirmés. L’intervenant affecté doit confirmer le transfert.",
  confirm: "Confirmer le transfert",
  refreshAck: "Vérifier la confirmation du canal de l’autre personne",
  confirmHint:
    "L’intervenant confirme en dernier afin de recevoir ici la preuve des deux canaux.",
  transferFailed: "Échec de connexion — remettre en file",
  observe: "Observer pendant cinq minutes",
  prepareInterrupt: "Préparer une interruption",
  interruptChoice:
    "Je souhaite interrompre cette conversation comme superviseur. L’observation seule ne permet pas la prise de contrôle.",
  confirmInterrupt: "Confirmer la portée d’interruption pour cinq minutes",
  interruptReady:
    "La portée d’interruption est confirmée. Actualisez la conversation avant la prise de contrôle.",
  takeover: "Prendre le contrôle comme superviseur responsable",
  takeoverHint:
    "La prise de contrôle bloque l’ancien responsable. Une nouvelle confirmation des canaux est nécessaire avant l’état connecté.",
  message: "Message manuel",
  send: "Envoyer le message manuel",
  conversation: "Conversation actuellement autorisée",
  noMessages: "Aucun message visible.",
  more: "Des messages antérieurs sont disponibles. Chargez la page suivante.",
  next: "Charger les messages antérieurs",
  author: "Auteur",
  source: "Attribution",
  invalidId: "Saisissez un identifiant de conversation complet.",
  active: "Saisie fictive active",
  human_requested: "Soutien humain demandé",
  queued: "En attente dans la file de soutien",
  worker_assigned: "Intervenant affecté — connexion non confirmée",
  handoff_pending: "Confirmation des deux canaux en attente",
  human_controlled: "Conversation sous contrôle humain",
  endedPhase: "Conversation terminée par choix explicite",
};
export const manualMessages: Record<Locale, Text> = {
  "en-CA": en,
  "fr-CA": fr,
};
