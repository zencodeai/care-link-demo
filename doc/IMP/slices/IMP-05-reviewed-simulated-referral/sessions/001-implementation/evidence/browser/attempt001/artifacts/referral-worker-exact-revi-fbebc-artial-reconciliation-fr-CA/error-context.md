# Instructions

- Following Playwright test failed.
- Explain why, be concise, respect Playwright best practices.
- Provide a snippet of code with the fix, if possible.

# Test info

- Name: referral.spec.ts >> worker exact review, uncertain delivery and partial reconciliation fr-CA
- Location: tests/e2e/referral/referral.spec.ts:96:3

# Error details

```
TimeoutError: locator.focus: Timeout 15000ms exceeded.
Call log:
  - waiting for getByRole('combobox', { name: 'Language', exact: true })

```

# Page snapshot

```yaml
- main [ref=e3]:
  - generic [ref=e4]:
    - paragraph [ref=e5]: CARE-Link
    - heading "Orientations examinées" [level=1] [ref=e6]
    - paragraph [ref=e7]: Démonstration privée avec données synthétiques · services destinataires fictifs seulement
    - generic [ref=e8]: Langue
    - combobox "Langue" [ref=e9]:
      - option "English"
      - option "Français" [selected]
  - region "Compte actuel" [ref=e10]:
    - heading "Compte actuel" [level=2] [ref=e11]
    - status [ref=e12]: Connectez-vous au service de compte, puis vérifiez votre compte.
    - button "Vérifier le compte" [ref=e13] [cursor=pointer]
  - navigation "Orientations examinées" [ref=e14]:
    - button "Consentement du client" [ref=e15] [cursor=pointer]
    - button "Examen de l'intervenant" [pressed] [ref=e16] [cursor=pointer]
    - button "Service destinataire" [ref=e17] [cursor=pointer]
  - generic [ref=e18]:
    - region "Examen de l'intervenant" [ref=e19]:
      - heading "Examen de l'intervenant" [level=2] [ref=e20]
      - generic [ref=e21]:
        - generic [ref=e22]: Identifiant de la séance de soutien
        - textbox "Identifiant de la séance de soutien" [disabled] [ref=e23]
        - button "Charger la séance actuelle" [disabled] [ref=e24]
      - button "Charger les options destinataires" [disabled] [ref=e26]
      - generic [ref=e27]:
        - generic [ref=e28]: Identifiant du service fictif
        - textbox "Identifiant du service fictif" [disabled] [ref=e29]
        - button "Charger l'option destinataire actuelle" [disabled] [ref=e30]
      - generic [ref=e31]:
        - generic [ref=e32]: Identifiant de l'orientation
        - textbox "Identifiant de l'orientation" [disabled] [ref=e33]
        - button "Ouvrir l'orientation actuelle" [disabled] [ref=e34]
    - region "Identifiant de l'envoi" [ref=e35]:
      - heading "Identifiant de l'envoi" [level=2] [ref=e36]
      - generic [ref=e37]:
        - generic [ref=e38]: Identifiant de l'envoi
        - textbox "Identifiant de l'envoi" [disabled] [ref=e39]
        - button "Ouvrir l'envoi actuel" [disabled] [ref=e40]
      - paragraph [ref=e41]: Un accusé de transport ne confirme pas l'acceptation du service. L'acceptation ne confirme pas la connexion avec une personne. Maintenez le soutien au client.
```

# Test source

```ts
  1   | import { test, expect, type Page } from "@playwright/test";
  2   | import AxeBuilder from "@axe-core/playwright";
  3   | import {
  4   |   messages,
  5   |   type Locale,
  6   | } from "../../../apps/web/src/referrals/messages";
  7   | import {
  8   |   installFixture,
  9   |   sid,
  10  |   service,
  11  |   rid,
  12  |   consentId,
  13  |   did,
  14  |   ceremonyId,
  15  |   sourceId,
  16  |   digest,
  17  |   reviewId,
  18  |   versions,
  19  | } from "./fixtures";
  20  | async function activate(page: Page, name: string) {
  21  |   const button = page.getByRole("button", { name, exact: true });
  22  |   await button.focus();
  23  |   await expect(button).toBeFocused();
  24  |   await page.keyboard.press("Enter");
  25  |   await expect(
  26  |     page.getByRole("button", {
  27  |       name: /^(Check account|Vérifier le compte)$/,
  28  |       exact: true,
  29  |     }),
  30  |   ).toBeEnabled();
  31  | }
  32  | async function initialize(page: Page, locale: Locale, path = "/referrals") {
  33  |   await page.goto(path);
  34  |   const language = page.getByRole("combobox", {
  35  |     name: "Language",
  36  |     exact: true,
  37  |   });
  38  |   await language.selectOption(locale);
> 39  |   await language.focus();
      |                  ^ TimeoutError: locator.focus: Timeout 15000ms exceeded.
  40  |   await page.keyboard.press("Tab");
  41  |   await expect(
  42  |     page.getByRole("button", { name: messages[locale].check, exact: true }),
  43  |   ).toBeFocused();
  44  |   await page.keyboard.press("Enter");
  45  |   await expect(
  46  |     page.getByText(messages[locale].done, { exact: true }),
  47  |   ).toBeVisible();
  48  | }
  49  | async function accessibilityAndReflow(
  50  |   page: Page,
  51  |   actor: string,
  52  |   locale: Locale,
  53  | ) {
  54  |   const rows: {
  55  |     width: number;
  56  |     scrollWidth: number;
  57  |     violations: string[];
  58  |     incomplete: string[];
  59  |   }[] = [];
  60  |   for (const width of [1280, 640]) {
  61  |     await page.setViewportSize({ width, height: 900 });
  62  |     const scrollWidth = await page.evaluate(
  63  |       () => document.documentElement.scrollWidth,
  64  |     );
  65  |     expect(scrollWidth).toBeLessThanOrEqual(width);
  66  |     const result = await new AxeBuilder({ page })
  67  |       .withTags(["wcag2a", "wcag2aa", "wcag21aa"])
  68  |       .analyze();
  69  |     rows.push({
  70  |       width,
  71  |       scrollWidth,
  72  |       violations: result.violations.map((value) => value.id),
  73  |       incomplete: result.incomplete.map((value) => value.id),
  74  |     });
  75  |     expect(result.violations).toEqual([]);
  76  |   }
  77  |   await test
  78  |     .info()
  79  |     .attach(`${actor}-${locale}-automated-accessibility.json`, {
  80  |       contentType: "application/json",
  81  |       body: JSON.stringify(
  82  |         {
  83  |           environment:
  84  |             "isolated Chromium with mocked synthetic API and provider; HTTP loopback only",
  85  |           browser: "Chromium",
  86  |           native_200_percent_zoom: "not_tested",
  87  |           human_review: "deferred_until_after_IMP10",
  88  |           rows,
  89  |         },
  90  |         null,
  91  |         2,
  92  |       ),
  93  |     });
  94  | }
  95  | for (const locale of ["en-CA", "fr-CA"] as const) {
  96  |   test(`worker exact review, uncertain delivery and partial reconciliation ${locale}`, async ({
  97  |     page,
  98  |   }) => {
  99  |     const fixture = await installFixture(page, "worker"),
  100 |       text = messages[locale];
  101 |     await initialize(page, locale);
  102 |     await page
  103 |       .getByRole("textbox", { name: text.session, exact: true })
  104 |       .fill(sid);
  105 |     await activate(page, text.load);
  106 |     await activate(page, text.findOptions);
  107 |     await page
  108 |       .getByRole("combobox", { name: text.chooseOption, exact: true })
  109 |       .selectOption(service);
  110 |     const source = page.getByRole("checkbox", {
  111 |       name: new RegExp(`${text.labels.needs} · Synthetic`),
  112 |     });
  113 |     await source.focus();
  114 |     await page.keyboard.press("Space");
  115 |     await expect(source).toBeChecked();
  116 |     await activate(page, text.draft);
  117 |     await expect(
  118 |       page.getByText(`${text.digest}: ${digest}`, { exact: true }),
  119 |     ).toBeVisible();
  120 |     await expect(
  121 |       page.getByText("Fictional option; capacity is unknown", { exact: true }),
  122 |     ).toBeVisible();
  123 |     await page
  124 |       .getByRole("textbox", { name: text.consent, exact: true })
  125 |       .fill(consentId);
  126 |     await activate(page, text.loadConsent);
  127 |     await activate(page, text.approve);
  128 |     await activate(page, text.enqueue);
  129 |     await expect(page.getByText(text.pending, { exact: true })).toBeVisible();
  130 |     expect(
  131 |       fixture.mutations.some((value) => value.path.endsWith("/send")),
  132 |     ).toBe(false);
  133 |     await activate(page, text.send);
  134 |     await expect(
  135 |       page.getByText(text.unresolved, { exact: true }),
  136 |     ).toBeVisible();
  137 |     await expect(
  138 |       page.getByRole("button", { name: text.send, exact: true }),
  139 |     ).toHaveCount(0);
```