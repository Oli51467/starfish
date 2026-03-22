import { computed, ref, watch } from 'vue';

import { GENERATED_ZH_EN } from './generatedZhEn';
import { EN_FIXUPS, MANUAL_EN_ZH, MANUAL_ZH_EN, TOKEN_ZH_EN } from './manualDictionary';

const LOCALE_STORAGE_KEY = 'starfish:ui-locale';
const TRANSLATABLE_ATTRIBUTES = ['title', 'aria-label', 'placeholder', 'alt'];

const textOriginalMap = new WeakMap();
const attrOriginalMap = new WeakMap();

let observer = null;
let initialized = false;
let scheduled = false;
let disabled = false;

function disableRuntimeI18n(error) {
  if (disabled) return;
  disabled = true;
  stopLocaleObserver();
  if (typeof console !== 'undefined' && typeof console.error === 'function') {
    console.error('[runtime-i18n] disabled due to runtime error:', error);
  }
}

function safeInvoke(fn) {
  if (disabled) return;
  try {
    fn();
  } catch (error) {
    disableRuntimeI18n(error);
  }
}

function normalizeLocale(rawValue) {
  const safe = String(rawValue || '').trim().toLowerCase();
  return safe === 'en' ? 'en' : 'zh';
}

function loadLocale() {
  if (typeof window === 'undefined') return 'zh';
  try {
    const stored = window.localStorage.getItem(LOCALE_STORAGE_KEY);
    return normalizeLocale(stored);
  } catch (error) {
    void error;
    return 'zh';
  }
}

export const locale = ref(loadLocale());
export const isEnglish = computed(() => locale.value === 'en');

function persistLocale(nextLocale) {
  if (typeof window === 'undefined') return;
  try {
    window.localStorage.setItem(LOCALE_STORAGE_KEY, normalizeLocale(nextLocale));
  } catch (error) {
    void error;
    // Ignore storage write errors.
  }
}

function containsChinese(text) {
  return /[\u4e00-\u9fff]/.test(String(text || ''));
}

function normalizeSpaces(text) {
  return String(text || '')
    .replace(/[\u00A0\u2000-\u200B]+/g, ' ')
    .replace(/\s{2,}/g, ' ')
    .trim();
}

function preserveLeadingTrailingWhitespace(source, translated) {
  const safeSource = String(source || '');
  const leadingMatch = safeSource.match(/^\s*/);
  const trailingMatch = safeSource.match(/\s*$/);
  const leading = Array.isArray(leadingMatch) ? String(leadingMatch[0] || '') : '';
  const trailing = Array.isArray(trailingMatch) ? String(trailingMatch[0] || '') : '';
  return `${leading}${translated}${trailing}`;
}

function applyEnglishFixups(text) {
  let next = String(text || '');
  for (const [from, to] of Object.entries(EN_FIXUPS)) {
    const regex = new RegExp(from.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'), 'gi');
    next = next.replace(regex, to);
  }
  return next;
}

function replaceByMap(text, dictionary) {
  let next = String(text || '');
  const entries = Object.entries(dictionary || {}).sort((a, b) => b[0].length - a[0].length);
  for (const [from, to] of entries) {
    if (!from) continue;
    next = next.split(from).join(to);
  }
  return next;
}

function runZhEnPatternRules(text) {
  let next = String(text || '');

  next = next.replace(/^共\s*(\d+)\s*条$/g, (_, count) => `Total ${count}`);
  next = next.replace(/^近\s*(\d+)\s*年$/g, (_, years) => `Last ${years} Years`);
  next = next.replace(
    /^第\s*(\d+)\s*轮协商已启动：正在评估\s*(.+)\s*的执行候选。$/g,
    (_, round, task) => `Round ${round} started: evaluating candidates for ${task}.`
  );
  next = next.replace(
    /^收到候选方案：(.+)（置信度\s*([^，]+)，预计耗时\s*([^，]+)，预计成本\s*([^）]+)）。$/g,
    (_, agent, confidence, latency, cost) => `Candidate received: ${agent} (confidence ${confidence}, latency ${latency}, cost ${cost}).`
  );
  next = next.replace(/^已授予执行合约：(.+)。$/g, (_, agent) => `Contract awarded: ${agent}.`);
  next = next.replace(
    /^预算更新：已使用\s*([^/]+)\s*\/\s*([^，]+)，剩余\s*(.+)。$/g,
    (_, spent, limit, remaining) => `Budget update: spent ${spent.trim()} / ${limit.trim()}, remaining ${remaining.trim()}.`
  );
  next = next.replace(/^审核结论：(.+)$/g, (_, reason) => `Review: ${reason}`);
  next = next.replace(/^第\s*(\d+)\s*次重试：(.+)$/g, (_, retryCount, reason) => `Retry ${retryCount}: ${reason}`);
  next = next.replace(/^已筛选\s*(\d+)\s*篇相关论文。$/g, (_, count) => `${count} relevant papers selected.`);
  next = next.replace(/^血缘树已生成，关联论文\s*(\d+)\s*篇。$/g, (_, count) => `Lineage tree generated with ${count} linked papers.`);

  return next;
}

function normalizeZhPunctuationToEn(text) {
  return String(text || '')
    .replace(/，/g, ', ')
    .replace(/。/g, '.')
    .replace(/：/g, ': ')
    .replace(/；/g, '; ')
    .replace(/（/g, '(')
    .replace(/）/g, ')')
    .replace(/、/g, ', ')
    .replace(/？/g, '?')
    .replace(/！/g, '!')
    .replace(/\s{2,}/g, ' ')
    .trim();
}

function translateZhToEn(rawText) {
  const source = String(rawText || '');
  if (!containsChinese(source)) return source;

  const compact = normalizeSpaces(source);
  const manual = MANUAL_ZH_EN[compact];
  if (manual) {
    return preserveLeadingTrailingWhitespace(source, applyEnglishFixups(manual));
  }

  const generated = GENERATED_ZH_EN[compact];
  if (generated) {
    return preserveLeadingTrailingWhitespace(source, applyEnglishFixups(generated));
  }

  let translated = compact;
  translated = runZhEnPatternRules(translated);
  translated = replaceByMap(translated, TOKEN_ZH_EN);
  translated = normalizeZhPunctuationToEn(translated);
  translated = applyEnglishFixups(translated);

  return preserveLeadingTrailingWhitespace(source, translated || compact);
}

function translateEnToZh(rawText) {
  const source = String(rawText || '');
  const compact = normalizeSpaces(source);
  const mapped = MANUAL_EN_ZH[compact];
  if (!mapped) return source;
  return preserveLeadingTrailingWhitespace(source, mapped);
}

function isSkippableElement(element) {
  if (!(element instanceof Element)) return true;
  if (element.closest('[data-i18n-skip="true"]')) return true;
  const tagName = String(element.tagName || '').toLowerCase();
  return tagName === 'script' || tagName === 'style' || tagName === 'noscript' || tagName === 'textarea';
}

function ensureAttrOriginalMap(element) {
  let snapshot = attrOriginalMap.get(element);
  if (!snapshot) {
    snapshot = new Map();
    attrOriginalMap.set(element, snapshot);
  }
  return snapshot;
}

function processTextNode(node) {
  if (!(node instanceof Text)) return;
  if (!node.nodeValue || !node.nodeValue.trim()) return;
  if (isSkippableElement(node.parentElement)) return;

  if (locale.value === 'en') {
    if (!textOriginalMap.has(node)) {
      textOriginalMap.set(node, node.nodeValue);
    }
    const mappedBase = textOriginalMap.get(node);
    const base = mappedBase === undefined || mappedBase === null ? node.nodeValue : mappedBase;
    const translated = translateZhToEn(base);
    if (translated !== node.nodeValue) {
      node.nodeValue = translated;
    }
    return;
  }

  const original = textOriginalMap.get(node);
  if (typeof original === 'string') {
    if (node.nodeValue !== original) {
      node.nodeValue = original;
    }
    return;
  }

  const translated = translateEnToZh(node.nodeValue);
  if (translated !== node.nodeValue) {
    node.nodeValue = translated;
  }
}

function processElementAttributes(element) {
  if (!(element instanceof Element)) return;
  if (isSkippableElement(element)) return;

  const attrSnapshot = ensureAttrOriginalMap(element);
  for (const name of TRANSLATABLE_ATTRIBUTES) {
    const currentValue = element.getAttribute(name);
    if (!currentValue || !currentValue.trim()) continue;

    if (locale.value === 'en') {
      if (!attrSnapshot.has(name)) {
        attrSnapshot.set(name, currentValue);
      }
      const mappedBase = attrSnapshot.get(name);
      const base = mappedBase === undefined || mappedBase === null ? currentValue : mappedBase;
      const translated = translateZhToEn(base);
      if (translated !== currentValue) {
        element.setAttribute(name, translated);
      }
      continue;
    }

    if (attrSnapshot.has(name)) {
      const original = attrSnapshot.get(name);
      if (typeof original === 'string' && original !== currentValue) {
        element.setAttribute(name, original);
      }
      continue;
    }

    const translated = translateEnToZh(currentValue);
    if (translated !== currentValue) {
      element.setAttribute(name, translated);
    }
  }
}

function processNodeTree(rootNode) {
  if (!rootNode) return;

  if (rootNode instanceof Text) {
    processTextNode(rootNode);
    return;
  }

  if (!(rootNode instanceof Element)) return;

  processElementAttributes(rootNode);

  const textWalker = document.createTreeWalker(rootNode, NodeFilter.SHOW_TEXT);
  let textNode = textWalker.nextNode();
  while (textNode) {
    processTextNode(textNode);
    textNode = textWalker.nextNode();
  }

  const elementWalker = document.createTreeWalker(rootNode, NodeFilter.SHOW_ELEMENT);
  let elementNode = elementWalker.nextNode();
  while (elementNode) {
    processElementAttributes(elementNode);
    elementNode = elementWalker.nextNode();
  }
}

function applyLocaleToDocument() {
  if (disabled) return;
  if (typeof document === 'undefined') return;
  const nextLocale = normalizeLocale(locale.value);
  locale.value = nextLocale;

  const html = document.documentElement;
  html.setAttribute('lang', nextLocale === 'en' ? 'en' : 'zh-CN');
  html.setAttribute('data-ui-locale', nextLocale);

  processNodeTree(document.body || html);
}

function scheduleApplyLocaleToDocument() {
  if (disabled) return;
  if (typeof window === 'undefined') return;
  if (scheduled) return;
  scheduled = true;
  window.requestAnimationFrame(() => {
    scheduled = false;
    safeInvoke(() => {
      applyLocaleToDocument();
    });
  });
}

function startObserver() {
  if (disabled) return;
  if (typeof window === 'undefined' || typeof document === 'undefined') return;
  if (observer || !document.body) return;

  observer = new MutationObserver((mutations) => {
    safeInvoke(() => {
      for (const mutation of mutations) {
        if (mutation.type === 'characterData') {
          processTextNode(mutation.target);
          continue;
        }

        if (mutation.type === 'attributes' && mutation.target instanceof Element) {
          processElementAttributes(mutation.target);
          continue;
        }

        if (mutation.type === 'childList') {
          for (const node of mutation.addedNodes) {
            processNodeTree(node);
          }
        }
      }
    });
  });

  observer.observe(document.body, {
    childList: true,
    subtree: true,
    characterData: true,
    attributes: true,
    attributeFilter: TRANSLATABLE_ATTRIBUTES,
  });
}

export function stopLocaleObserver() {
  if (!observer) return;
  observer.disconnect();
  observer = null;
}

export function initRuntimeI18n() {
  if (initialized) return;
  initialized = true;

  watch(
    locale,
    (nextValue) => {
      const normalized = normalizeLocale(nextValue);
      if (normalized !== nextValue) {
        locale.value = normalized;
        return;
      }
      persistLocale(normalized);
      safeInvoke(() => {
        scheduleApplyLocaleToDocument();
      });
    },
    { immediate: true }
  );

  if (typeof document === 'undefined') return;

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', () => {
      safeInvoke(() => {
        startObserver();
        applyLocaleToDocument();
      });
    }, { once: true });
    return;
  }

  safeInvoke(() => {
    startObserver();
    applyLocaleToDocument();
  });
}

export function setLocale(nextLocale) {
  locale.value = normalizeLocale(nextLocale);
}

export function toggleLocale() {
  locale.value = locale.value === 'en' ? 'zh' : 'en';
}

export function useRuntimeLocale() {
  return {
    locale,
    isEnglish,
    setLocale,
    toggleLocale,
  };
}
