# Instructions

- Following Playwright test failed.
- Explain why, be concise, respect Playwright best practices.
- Provide a snippet of code with the fix, if possible.

# Test info

- Name: referral.spec.ts >> receiver field-specific decision fr-CA
- Location: tests/e2e/referral/referral.spec.ts:165:3

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
    - button "Examen de l'intervenant" [ref=e16] [cursor=pointer]
    - button "Service destinataire" [pressed] [ref=e17] [cursor=pointer]
  - region "Boîte de réception" [ref=e19]:
    - heading "Boîte de réception" [level=2] [ref=e20]
    - paragraph [ref=e21]: Les décisions appartiennent au service destinataire actuel. Choisissez seulement les champs que ce service accepte.
    - button "Actualiser la boîte de réception" [disabled] [ref=e23]
    - generic [ref=e24]:
      - generic [ref=e25]: Identifiant de l'envoi
      - textbox "Identifiant de l'envoi" [disabled] [ref=e26]
      - button "Actualiser le contenu actuel" [disabled] [ref=e27]
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
> 39  |   await page
      |                  ^ TimeoutError: locator.focus: Timeout 15000ms exceeded.
  40  |     .getByRole("combobox", { name: messages[locale].language, exact: true })
  41  |     .focus();
  42  |   await page.keyboard.press("Tab");
  43  |   await expect(
  44  |     page.getByRole("button", { name: messages[locale].check, exact: true }),
  45  |   ).toBeFocused();
  46  |   await page.keyboard.press("Enter");
  47  |   await expect(
  48  |     page.getByText(messages[locale].done, { exact: true }),
  49  |   ).toBeVisible();
  50  | }
  51  | async function accessibilityAndReflow(
  52  |   page: Page,
  53  |   actor: string,
  54  |   locale: Locale,
  55  | ) {
  56  |   const rows: {
  57  |     width: number;
  58  |     scrollWidth: number;
  59  |     violations: string[];
  60  |     incomplete: string[];
  61  |   }[] = [];
  62  |   for (const width of [1280, 640]) {
  63  |     await page.setViewportSize({ width, height: 900 });
  64  |     const scrollWidth = await page.evaluate(
  65  |       () => document.documentElement.scrollWidth,
  66  |     );
  67  |     expect(scrollWidth).toBeLessThanOrEqual(width);
  68  |     const result = await new AxeBuilder({ page })
  69  |       .withTags(["wcag2a", "wcag2aa", "wcag21aa"])
  70  |       .analyze();
  71  |     rows.push({
  72  |       width,
  73  |       scrollWidth,
  74  |       violations: result.violations.map((value) => value.id),
  75  |       incomplete: result.incomplete.map((value) => value.id),
  76  |     });
  77  |     expect(result.violations).toEqual([]);
  78  |   }
  79  |   await test.info().attach(`${actor}-${locale}-automated-accessibility.json`, {
  80  |     contentType: "application/json",
  81  |     body: JSON.stringify(
  82  |       {
  83  |         environment:
  84  |           "isolated Chromium with mocked synthetic API and provider; HTTP loopback only",
  85  |         browser: "Chromium",
  86  |         native_200_percent_zoom: "not_tested",
  87  |         human_review: "deferred_until_after_IMP10",
  88  |         rows,
  89  |       },
  90  |       null,
  91  |       2,
  92  |     ),
  93  |   });
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