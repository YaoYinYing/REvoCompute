import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { applyLocale, catalogs, initialLocale, locale, locales, storedLocale, t, translate } from '../src/app/i18n';

function memoryStorage(): Storage {
  const map = new Map<string, string>();
  return {
    get length() { return map.size; },
    clear: () => map.clear(),
    getItem: (key: string) => map.get(key) ?? null,
    key: (index: number) => [...map.keys()][index] ?? null,
    removeItem: (key: string) => { map.delete(key); },
    setItem: (key: string, value: string) => { map.set(key, String(value)); },
  } as Storage;
}

let root: { lang: string };

beforeEach(() => {
  root = { lang: '' };
  vi.stubGlobal('localStorage', memoryStorage());
  vi.stubGlobal('document', { documentElement: root });
  vi.stubGlobal('navigator', { language: 'en-US' });
});
afterEach(() => { vi.unstubAllGlobals(); });

describe('frontend localization', () => {
  it('translates frontend-owned copy and falls back deterministically to English', () => {
    expect(translate('en', 'shell.nav.dashboard')).toBe('Dashboard');
    expect(translate('zh-CN', 'shell.nav.dashboard')).toBe('任务面板');
    // An unknown locale and an unknown key both fall back rather than throwing.
    expect(translate('fr' as never, 'shell.nav.dashboard')).toBe('Dashboard');
    expect(translate('en', 'nonexistent.key')).toBe('nonexistent.key');
  });

  it('interpolates params without string concatenation', () => {
    expect(translate('en', 'dashboard.list.count', { shown: 3, total: 9 })).toBe('3 of 9 tasks');
    expect(translate('zh-CN', 'dashboard.list.count', { shown: 3, total: 9 })).toBe('共 9 个任务，显示 3 个');
    // A missing param is left intact rather than becoming "undefined".
    expect(translate('en', 'dashboard.list.count', { shown: 3 })).toContain('{total}');
  });

  it('prefers an explicit choice, then the browser preference, then English', () => {
    expect(storedLocale()).toBeNull();
    expect(initialLocale()).toBe('en');
    vi.stubGlobal('navigator', { language: 'zh-CN' });
    expect(initialLocale()).toBe('zh-CN');
    applyLocale('zh-CN');
    expect(storedLocale()).toBe('zh-CN');
    expect(initialLocale()).toBe('zh-CN');
    expect(root.lang).toBe('zh-CN');
    expect(locale()).toBe('zh-CN');
    expect(t('shell.nav.dashboard')).toBe('任务面板');
  });

  it('offers exactly the app-owned locales', () => {
    expect(locales.map(item => item.id)).toEqual(['en', 'zh-CN']);
  });

  it('keeps the English and Simplified Chinese catalogs in exact 1:1 parity', () => {
    const englishKeys = Object.keys(catalogs.en);
    const chineseKeys = Object.keys(catalogs['zh-CN']);
    // Same key set, same order, no duplicates: a partial catalog would let one
    // surface fall back to English under zh-CN, which 11 forbids.
    expect(chineseKeys).toEqual(englishKeys);
    expect(new Set(chineseKeys).size).toBe(chineseKeys.length);
    for (const key of englishKeys) {
      expect(catalogs['zh-CN'][key], key).toBeTruthy();
      expect(catalogs.en[key], key).toBeTruthy();
    }
  });

  it('authors the Account Quota page and its navigation label in both locales', () => {
    // The new destination is authored copy, not a key that falls back: the label
    // and the page's own heading are distinct, real strings in both catalogs.
    expect(translate('en', 'shell.account.quota')).toBe('Quota');
    expect(translate('zh-CN', 'shell.account.quota')).toBe('资源配额');
    expect(translate('en', 'quota.title')).toBe('Quota');
    expect(translate('zh-CN', 'quota.title')).toBe('资源配额');
    for (const key of ['quota.description', 'quota.loading', 'quota.usage.heading', 'quota.error.generic']) {
      expect(translate('en', key), key).not.toBe(key);
      expect(translate('zh-CN', key), key).not.toBe(key);
      expect(translate('zh-CN', key)).not.toBe(translate('en', key));
    }
  });

  it('localizes every guided-tour step, not only the tour controls', () => {
    for (const key of ['dashboard', 'lifecycle', 'runners', 'create', 'result']) {
      const title = 'tour.step.' + key + '.title';
      const body = 'tour.step.' + key + '.body';
      const englishTitle = translate('en', title);
      const chineseTitle = translate('zh-CN', title);
      // A tour step is authored copy in both catalogs: neither locale falls back to
      // the key itself, and the English and Chinese titles are genuinely distinct.
      expect(englishTitle).not.toBe(title);
      expect(chineseTitle).not.toBe(title);
      expect(chineseTitle).not.toBe(englishTitle);
      expect(translate('en', body)).not.toBe(body);
      expect(translate('zh-CN', body)).not.toBe(body);
    }
  });
});
