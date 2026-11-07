export const messages = {
  "en-CA": {
    title: "CARE-Link developer shell",
    eyebrow: "IMP-01 · Synthetic demonstration",
    intro:
      "Explore contract validation and the development API. Participant services are unavailable.",
    language: "Language",
    capabilities: "API capabilities",
    loading: "Checking the development API…",
    unavailable:
      "API unconnected. Start the local development API, then retry.",
    invalid: "The API returned an incompatible capability result.",
    connected: "Development API connected",
    scope:
      "Contract validation is available. Participant admission and business operations are unavailable.",
    retry: "Check API again",
    preview: "Role preview",
    participant: "Participant",
    worker: "Worker",
    supervisor: "Supervisor",
    previewNotice:
      "This preview changes the display only. It does not sign in or grant access.",
    participantNotice:
      "Participant conversations, plans, and referrals are unavailable.",
    workerNotice: "Worker queues and assignments are unavailable.",
    supervisorNotice: "Supervisor controls are unavailable.",
    contracts: "Contract demonstration",
    contract: "Contract",
    input: "JSON input",
    validate: "Validate locally",
    valid: "Valid contract input. No operation was performed.",
    rejected:
      "Input rejected. Check required fields, unknown keys, JSON syntax, and revision limits.",
    privacy:
      "Use fictional input only. This shell stores no input in browser storage.",
    hint: "Revisions are decimal strings from 0 to 9223372036854775807. Nested unknown keys are rejected.",
  },
  "fr-CA": {
    title: "Interface de développement CARE-Link",
    eyebrow: "IMP-01 · Démonstration synthétique",
    intro:
      "Explorez la validation des contrats et l’API de développement. Les services aux participants sont indisponibles.",
    language: "Langue",
    capabilities: "Capacités de l’API",
    loading: "Vérification de l’API de développement…",
    unavailable:
      "API non connectée. Démarrez l’API locale de développement, puis réessayez.",
    invalid: "L’API a renvoyé un résultat de capacité incompatible.",
    connected: "API de développement connectée",
    scope:
      "La validation des contrats est disponible. L’admission des participants et les opérations métier sont indisponibles.",
    retry: "Vérifier l’API à nouveau",
    preview: "Aperçu du rôle",
    participant: "Participant",
    worker: "Intervenant",
    supervisor: "Superviseur",
    previewNotice:
      "Cet aperçu modifie uniquement l’affichage. Il ne connecte personne et n’accorde aucun accès.",
    participantNotice:
      "Les conversations, les plans et les orientations des participants sont indisponibles.",
    workerNotice:
      "Les files d’attente et les affectations des intervenants sont indisponibles.",
    supervisorNotice: "Les commandes de supervision sont indisponibles.",
    contracts: "Démonstration des contrats",
    contract: "Contrat",
    input: "Saisie JSON",
    validate: "Valider localement",
    valid: "Saisie conforme au contrat. Aucune opération n’a été effectuée.",
    rejected:
      "Saisie rejetée. Vérifiez les champs obligatoires, les clés inconnues, la syntaxe JSON et les limites de révision.",
    privacy:
      "Utilisez uniquement des données fictives. Cette interface ne conserve aucune saisie dans le stockage du navigateur.",
    hint: "Les révisions sont des chaînes décimales de 0 à 9223372036854775807. Les clés imbriquées inconnues sont rejetées.",
  },
} as const;
