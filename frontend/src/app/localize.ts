import { createIcons, Languages, MoonStar, SunMedium } from 'lucide';
import { locale, locales, setLocale, t, type Locale } from './i18n';
import { cycleTheme, storedTheme, type ThemeMode } from './theme';

/*
 * Header controls shared by the authenticated and public shells.
 *
 * Both shells carry the same language and theme affordances. They are authored
 * once here so the two shells cannot drift: a fix to the language control (its
 * accessible name, its choices, the way it states the current language) reaches
 * every header that shows it.
 *
 * The language control is an icon button. The current language is already
 * announced by `document.documentElement.lang` and named by the control's own
 * accessible label only when a translated string states it; the compact top bar
 * must not spend a word-width slot restating it beside the icon.
 */

export function themeLabel(mode: ThemeMode): string {
  return `${t('shell.action.theme')}: ${t(`theme.${mode}`)}`;
}

/** The current theme, painted as an icon button that cycles auto → dark → light. */
export function themeButton(): HTMLButtonElement {
  const button = document.createElement('button');
  button.type = 'button';
  button.className = 'icon-button';
  const paint = (): void => {
    button.title = themeLabel(storedTheme());
    button.setAttribute('aria-label', button.title);
    button.innerHTML = `<i data-lucide="${document.documentElement.dataset.theme === 'dark' ? 'sun-medium' : 'moon-star'}" aria-hidden="true"></i>`;
    createIcons({ icons: { MoonStar, SunMedium }, root: button });
  };
  paint();
  button.addEventListener('click', () => { cycleTheme(); paint(); });
  return button;
}

/**
 * The language control: one icon button whose accessible name states the action
 * and the language, over a popover listing every locale. The choices stay in the
 * popover at every width; nothing narrows them to an icon-only summary.
 */
export function languageMenu(): HTMLElement {
  const details = document.createElement('details');
  details.className = 'lang-menu';
  const current = locales.find(item => item.id === locale())!;
  const summary = document.createElement('summary');
  summary.className = 'icon-button';
  summary.title = `${t('shell.action.language')}: ${current.label}`;
  summary.setAttribute('aria-label', summary.title);
  summary.innerHTML = '<i data-lucide="languages" aria-hidden="true"></i>';
  createIcons({ icons: { Languages }, root: summary });
  const options = document.createElement('div');
  options.className = 'lang-options';
  options.setAttribute('role', 'radiogroup');
  options.setAttribute('aria-label', t('shell.action.language'));
  locales.forEach(item => {
    const button = document.createElement('button');
    button.type = 'button'; button.setAttribute('role', 'radio'); button.setAttribute('aria-checked', String(item.id === locale()));
    button.dataset.locale = item.id;
    button.append(document.createTextNode(item.label));
    if (item.id === locale()) { const mark = document.createElement('i'); mark.dataset.lucide = 'check'; mark.setAttribute('aria-hidden', 'true'); button.append(mark); }
    button.addEventListener('click', () => setLocale(item.id as Locale));
    options.append(button);
  });
  details.append(summary, options);
  return details;
}
