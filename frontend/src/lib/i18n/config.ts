"use client";
import i18n from "i18next";
import { initReactI18next } from "react-i18next";
import LanguageDetector from "i18next-browser-languagedetector";

import commonEn from "./locales/en/common.json";
import commonZh from "./locales/zh/common.json";
import dashboardEn from "./locales/en/dashboard.json";
import dashboardZh from "./locales/zh/dashboard.json";
import loginEn from "./locales/en/login.json";
import loginZh from "./locales/zh/login.json";
import setupEn from "./locales/en/setup.json";
import setupZh from "./locales/zh/setup.json";
import securityEn from "./locales/en/security.json";
import securityZh from "./locales/zh/security.json";
import secretsEn from "./locales/en/secrets.json";
import secretsZh from "./locales/zh/secrets.json";
import settingsEn from "./locales/en/settings.json";
import settingsZh from "./locales/zh/settings.json";
import toolsEn from "./locales/en/tools.json";
import toolsZh from "./locales/zh/tools.json";
import skillEn from "./locales/en/skill.json";
import skillZh from "./locales/zh/skill.json";
import docsEn from "./locales/en/docs.json";
import docsZh from "./locales/zh/docs.json";
import scriptEn from "./locales/en/script.json";
import scriptZh from "./locales/zh/script.json";
import scriptEditorEn from "./locales/en/scriptEditor.json";
import scriptEditorZh from "./locales/zh/scriptEditor.json";
import scriptPanelsEn from "./locales/en/scriptPanels.json";
import scriptPanelsZh from "./locales/zh/scriptPanels.json";
import converseEn from "./locales/en/converse.json";
import converseZh from "./locales/zh/converse.json";
import assistantEn from "./locales/en/assistant.json";
import assistantZh from "./locales/zh/assistant.json";

export const LOCALE_STORAGE_KEY = "agentflow_locale";

// One namespace per page/component group — keeps translation files small and
// lets independent pages be edited without touching a shared giant JSON blob.
const resources = {
  en: {
    common: commonEn,
    dashboard: dashboardEn,
    login: loginEn,
    setup: setupEn,
    security: securityEn,
    secrets: secretsEn,
    settings: settingsEn,
    tools: toolsEn,
    skill: skillEn,
    docs: docsEn,
    script: scriptEn,
    scriptEditor: scriptEditorEn,
    scriptPanels: scriptPanelsEn,
    converse: converseEn,
    assistant: assistantEn,
  },
  zh: {
    common: commonZh,
    dashboard: dashboardZh,
    login: loginZh,
    setup: setupZh,
    security: securityZh,
    secrets: secretsZh,
    settings: settingsZh,
    tools: toolsZh,
    skill: skillZh,
    docs: docsZh,
    script: scriptZh,
    scriptEditor: scriptEditorZh,
    scriptPanels: scriptPanelsZh,
    converse: converseZh,
    assistant: assistantZh,
  },
} as const;

if (!i18n.isInitialized) {
  i18n
    .use(LanguageDetector)
    .use(initReactI18next)
    .init({
      resources,
      fallbackLng: "en",
      supportedLngs: ["en", "zh"],
      nonExplicitSupportedLngs: true, // "zh-CN"/"zh-TW" -> "zh"
      ns: Object.keys(resources.en),
      defaultNS: "common",
      detection: {
        order: ["localStorage", "navigator", "htmlTag"],
        caches: ["localStorage"],
        lookupLocalStorage: LOCALE_STORAGE_KEY,
      },
      interpolation: { escapeValue: false },
      react: { useSuspense: false },
    });
}

export default i18n;
