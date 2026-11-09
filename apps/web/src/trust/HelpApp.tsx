import { useEffect, useState } from "react";
import { TrustAndHelp } from "./TrustAndHelp";
import { trustMessages } from "./messages";

/** Build and serve this entry from the independent help origin/BFF. */
export function HelpApp() {
  const [locale, setLocale] = useState<keyof typeof trustMessages>("en-CA");
  const text = trustMessages[locale];
  useEffect(() => {
    document.documentElement.lang = locale;
    document.title = text.title;
  }, [locale, text.title]);
  return (
    <main>
      <header>
        <h1>{text.helpAccount}</h1>
        <label htmlFor="help-language">
          {locale === "en-CA" ? "Language" : "Langue"}
        </label>
        <select
          id="help-language"
          value={locale}
          onChange={(event) => {
            const value = event.target.value;
            if (value === "en-CA" || value === "fr-CA") setLocale(value);
          }}
        >
          <option value="en-CA">English</option>
          <option value="fr-CA">Français</option>
        </select>
      </header>
      <TrustAndHelp
        locale={locale}
        surface="help"
        oidcOrigin={import.meta.env.VITE_OIDC_ORIGIN ?? null}
        staticOrigin={import.meta.env.VITE_STATIC_ORIGIN ?? null}
      />
    </main>
  );
}
