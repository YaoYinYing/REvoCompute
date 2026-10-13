import type { ParameterDefinition } from './types';
import { t } from '../../app/i18n';

interface ParameterSchema {
  properties?: Record<string, unknown>;
  required?: string[];
  [key: string]: unknown;
}

function record(value: unknown): Record<string, unknown> {
  return value && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, unknown> : {};
}

/** Whether a declared JSON Schema ``format`` names an ISO calendar date. */
export function isIsoDate(value: unknown): boolean {
  return typeof value === 'string' && /^\d{4}-\d{2}-\d{2}$/.test(value);
}

export function parametersFromSchema(schema: ParameterSchema): ParameterDefinition[] {
  const required = new Set(schema.required || []);
  return Object.entries(schema.properties || {}).map(([name, raw]) => {
    const property = record(raw);
    const type = property.type === 'boolean' ? 'bool' : property.type === 'integer' ? 'int' : property.type === 'number' ? 'float' : 'string';
    const ui = record(property['x-ui-control']);
    const random = record(ui.random);
    return {
      name, type,
      // A declared ``format: date`` is the schema's own calendar-date contract.
      // The control only offers a date picker when the declared default can
      // inhabit one; a non-ISO default would be blanked by the picker, which
      // would silently drop the task's own default.
      dateFormat: property.format === 'date' && (property.default == null || isIsoDate(property.default)),
      label: typeof property.title === 'string' ? property.title : name.replaceAll('_', ' ').replace(/\b\w/g, letter => letter.toUpperCase()),
      description: typeof property.description === 'string' ? property.description : '',
      help: typeof property['x-help'] === 'string' ? property['x-help'] : '',
      unit: typeof property['x-unit'] === 'string' ? property['x-unit'] : '',
      required: required.has(name), defaultValue: property.default as string | number | boolean | undefined,
      choices: Array.isArray(property.enum) ? property.enum.filter((value): value is string | number | boolean => ['string', 'number', 'boolean'].includes(typeof value)) : [],
      minimum: typeof property.minimum === 'number' ? property.minimum : undefined,
      maximum: typeof property.maximum === 'number' ? property.maximum : undefined,
      exclusiveMinimum: typeof property.exclusiveMinimum === 'number' ? property.exclusiveMinimum : undefined,
      exclusiveMaximum: typeof property.exclusiveMaximum === 'number' ? property.exclusiveMaximum : undefined,
      step: typeof property.multipleOf === 'number' ? property.multipleOf : undefined,
      advanced: property['x-advanced'] === true,
      seed: ui.kind === 'seed' ? {
        minimum: typeof random.minimum === 'number' ? random.minimum : undefined,
        maximum: typeof random.maximum === 'number' ? random.maximum : undefined,
      } : undefined,
    };
  });
}

export function parameterValue(parameter: ParameterDefinition, control: HTMLInputElement | HTMLSelectElement): string {
  return parameter.type === 'bool' && control instanceof HTMLInputElement ? String(control.checked) : control.value;
}

/**
 * One uniform integer across a declared seed generation domain.
 *
 * The generation domain is the task's own ``x-ui-control.random`` bounds when it
 * declares them and its API-valid range otherwise, so a sentinel the schema keeps
 * manually valid is never generated. An exclusive bound is moved inside the range
 * rather than widened, and the domain is drawn by rejection so every value in it
 * is equally likely; the modulo alternative would over-represent the low end.
 *
 * The declared domain is at most ``2**32`` values - the owning ``task.yaml``
 * contract bounds a seed generation range to that width and the server refuses a
 * wider one - so a single 32-bit draw covers it exactly. A domain beyond that is
 * refused loudly rather than answered from only its low ``2**32`` values, which is
 * not the uniform coverage the declared range promises. The function is pure over
 * ``random`` so a caller owns the entropy source, and it returns the domain's lower
 * bound when the range is empty rather than escaping the declared bounds.
 */
export function seedConstant(
  parameter: ParameterDefinition,
  random: (target: Uint32Array) => Uint32Array,
): number {
  const atLeast = (value: number | undefined, fallback: number | undefined): number => {
    if (fallback == null) return value ?? 0;
    return value == null ? fallback : Math.max(value, fallback);
  };
  const atMost = (value: number | undefined, fallback: number | undefined): number => {
    if (fallback == null) return value ?? 2_147_483_647;
    return value == null ? fallback : Math.min(value, fallback);
  };
  let minimum = Math.ceil(atLeast(parameter.seed?.minimum, parameter.minimum));
  let maximum = Math.floor(atMost(parameter.seed?.maximum, parameter.maximum));
  if (parameter.seed?.minimum == null && parameter.exclusiveMinimum != null) minimum = Math.max(minimum, Math.floor(parameter.exclusiveMinimum) + 1);
  if (parameter.seed?.maximum == null && parameter.exclusiveMaximum != null) maximum = Math.min(maximum, Math.ceil(parameter.exclusiveMaximum) - 1);
  if (maximum < minimum) return minimum;
  const span = maximum - minimum + 1;
  // Fail loud on a domain no 32-bit draw spans uniformly, instead of presenting a
  // biased or incomplete sample of the range the owning schema published.
  if (span > 2 ** 32) throw new Error(`Seed generation domain ${minimum}..${maximum} is wider than a 32-bit draw`);
  const bound = 2 ** 32 - (2 ** 32 % span);
  const draw = new Uint32Array(1);
  for (;;) {
    random(draw);
    const value = draw[0]!;
    if (value < bound) return minimum + (value % span);
  }
}

export function validateParameter(parameter: ParameterDefinition, control: HTMLInputElement | HTMLSelectElement): string | null {
  const value = parameterValue(parameter, control);
  // The template frame is frontend-owned copy and follows the locale; the
  // interpolated `label` is the server's own parameter vocabulary and stays
  // verbatim in both locales.
  if (parameter.required && !value) return t('ct.param.required', { label: parameter.label });
  if (parameter.choices.length && !parameter.choices.some(choice => String(choice) === value)) return t('ct.param.choice', { label: parameter.label });
  if ((parameter.type === 'int' || parameter.type === 'float') && value) {
    const number = Number(value);
    if (!Number.isFinite(number) || (parameter.type === 'int' && !Number.isInteger(number))) return t(parameter.type === 'int' ? 'ct.param.integer' : 'ct.param.number', { label: parameter.label });
    if (parameter.minimum != null && number < parameter.minimum) return t('ct.param.minimum', { label: parameter.label, minimum: parameter.minimum });
    if (parameter.maximum != null && number > parameter.maximum) return t('ct.param.maximum', { label: parameter.label, maximum: parameter.maximum });
    // A declared exclusive bound is enforced on the side that has no inclusive
    // bound: a schema declaring both describes an empty range, and the inclusive
    // check above is the one that reports it, so the value is not stated twice.
    // The bound and the label stay the server's own, verbatim.
    if (parameter.minimum == null && parameter.exclusiveMinimum != null && number <= parameter.exclusiveMinimum) return t('ct.param.exclusiveMinimum', { label: parameter.label, bound: parameter.exclusiveMinimum });
    if (parameter.maximum == null && parameter.exclusiveMaximum != null && number >= parameter.exclusiveMaximum) return t('ct.param.exclusiveMaximum', { label: parameter.label, bound: parameter.exclusiveMaximum });
  }
  return control.checkValidity() ? null : (control.validationMessage || t('ct.param.invalid', { label: parameter.label }));
}
