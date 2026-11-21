import type { Text } from "./messages";
const labels: Record<string, [string, string]> = {
  registered: ["Registered", "Enregistré"],
  review_pending: ["Review pending", "Examen en attente"],
  approved: ["Approved", "Approuvé"],
  rejected: ["Rejected", "Refusé"],
  retired: ["Retired", "Retiré"],
  proposed: ["Proposed", "Proposé"],
  staged: ["Staged", "Préparé"],
  ready: ["Ready", "Prêt"],
  active: ["Active", "Actif"],
  superseded: ["Superseded", "Remplacé"],
  open: ["Open", "Ouvert"],
  contained: ["Contained", "Confiné"],
  reviewing: ["Under review", "En examen"],
  remediated: ["Remediated", "Corrigé"],
  closed: ["Closed", "Fermé"],
  release: ["Release", "Version de livraison"],
  policy: ["Policy", "Politique"],
  model: ["Model", "Modèle"],
  prompt: ["Prompt", "Instruction au modèle"],
  tool_registry: ["Tool registry", "Registre d’outils"],
  directory: ["Directory", "Répertoire"],
  content: ["Content", "Contenu"],
  config: ["Configuration", "Configuration"],
  scenario: ["Scenario", "Scénario"],
  migration: ["Migration", "Migration"],
  technical: ["Technical", "Technique"],
  stub: ["Synthetic stub", "Substitut synthétique"],
  reviewed_static: ["Reviewed static content", "Contenu statique examiné"],
  triage: ["Triage", "Triage"],
  thresholds: ["Thresholds", "Seuils"],
  consent: ["Consent", "Consentement"],
  disclosure: ["Disclosure", "Divulgation"],
  emergency_guard: ["Emergency guard", "Protection d’urgence"],
  tool_permissions: ["Tool permissions", "Permissions d’outils"],
  triage_features: ["Triage features", "Caractéristiques de triage"],
  protocol_content: ["Protocol content", "Contenu de protocole"],
  static_content: ["Static content", "Contenu statique"],
  jurisdiction: ["Jurisdiction", "Territoire"],
  infrastructure: ["Infrastructure", "Infrastructure"],
  security: ["Security", "Sécurité"],
  privacy: ["Privacy", "Vie privée"],
  operations: ["Operations", "Exploitation"],
  clinical: ["Clinical", "Clinique"],
  equity: ["Equity", "Équité"],
  community: ["Community", "Communauté"],
  contamination: ["Contamination", "Contamination"],
  outage: ["Outage", "Panne"],
  language: ["Language", "Langue"],
  governance: ["Governance", "Gouvernance"],
  info: ["Information", "Information"],
  warning: ["Warning", "Avertissement"],
  critical: ["Critical", "Critique"],
  operator: ["Operator", "Opérateur"],
  auditor: ["Auditor", "Auditeur"],
  supervisor: ["Supervisor", "Superviseur"],
  all: ["All", "Toutes"],
  "en-CA": ["English", "Anglais"],
  "fr-CA": ["French", "Français"],
  "CA-XX": ["Synthetic region XX", "Région synthétique XX"],
  "CA-YY": ["Synthetic region YY", "Région synthétique YY"],
  summary: ["Summary", "Résumé"],
  outcome: ["Outcome", "Résultat"],
  needs: ["Needs", "Besoins"],
  preferences: ["Preferences", "Préférences"],
  observations: ["Observations", "Observations"],
  rationale: ["Rationale", "Justification"],
  PERMIT: ["Permitted", "Permis"],
  DENY: ["Denied", "Refusé"],
  REQUIRE_HUMAN: ["Human review required", "Examen humain requis"],
  OBSERVED: ["Observed", "Observé"],
  committed: ["Committed", "Consigné"],
};
export function label(value: string, text: Text): string {
  return labels[value]?.[text.language === "Language" ? 0 : 1] ?? value;
}
export function State({ value, text }: { value: string; text: Text }) {
  return <>{label(value, text)}</>;
}
export function Choices({
  values,
  text,
}: {
  values: readonly string[];
  text: Text;
}) {
  return (
    <>
      {values.map((value) => (
        <option key={value} value={value}>
          {label(value, text)}
        </option>
      ))}
    </>
  );
}
