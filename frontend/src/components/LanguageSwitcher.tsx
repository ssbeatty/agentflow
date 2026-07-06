"use client";
import { useTranslation } from "react-i18next";
import { Languages } from "lucide-react";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";

const LANGUAGES = ["zh", "en"] as const;

export default function LanguageSwitcher() {
  const { t, i18n } = useTranslation("common");
  const current = LANGUAGES.includes(i18n.resolvedLanguage as (typeof LANGUAGES)[number])
    ? i18n.resolvedLanguage!
    : "en";

  return (
    <Select value={current} onValueChange={(v) => i18n.changeLanguage(v)}>
      <SelectTrigger className="w-36">
        <Languages className="h-4 w-4 mr-1.5 opacity-70 shrink-0" />
        <SelectValue />
      </SelectTrigger>
      <SelectContent>
        {LANGUAGES.map((code) => (
          <SelectItem key={code} value={code}>{t(`language.${code}`)}</SelectItem>
        ))}
      </SelectContent>
    </Select>
  );
}
