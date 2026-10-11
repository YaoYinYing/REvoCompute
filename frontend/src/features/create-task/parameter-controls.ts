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

export function parametersFromSchema(schema: ParameterSchema): ParameterDefinition[] {
  const required = new Set(schema.required || []);
  return Object.entries(schema.properties || {}).map(([name, raw]) => {
    const property = record(raw);
    const type = property.type === 'boolean' ? 'bool' : property.type === 'integer' ? 'int' : property.type === 'number' ? 'float' : 'string';
    const ui = record(property['x-ui-control']);
    const random = record(ui.random);
    return {
      name, type,
      label: typeof property.title === 'string' ? property.title : name.replaceAll('_', ' ').replace(/\b\w/g, letter => letter.toUpperCase()),
      description: typeof property.description === 'string' ? property.description : '',
      help: typeof property['x-help'] === 'string' ? property['x-help'] : '',
      unit: typeof property['x-unit'] === 'string' ? property['x-unit'] : '',
      required: required.has(name), defaultValue: property.default as string | number | boolean | undefined,
      choices: Array.isArray(property.enum) ? property.enum.filter((value): value is string | number | boolean => ['string', 'number', 'boolean'].includes(typeof value)) : [],
      minimum: typeof property.minimum === 'number' ? property.minimum : undefined,
      maximum: typeof property.maximum === 'number' ? property.maximum : undefined,
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

export function validateParameter(parameter: ParameterDefinition, control: HTMLInputElement | HTMLSelectElement): string | null {
  const value = parameterValue(parameter, control);
  // The template frame is frontend-owned copy and follows the locale; the
  // interpolated `label` is the server's own parameter vocabulary and stays
  // verbatim in both locales.
  if (parameter.required && !value) return t('ct.param.required', { label: parameter.label });
  if (parameter.choices.length && !parameter.choices.some(choice => String(choice) === value)) return t('ct.param.choice', { label: parameter.label.toLowerCase() });
  if ((parameter.type === 'int' || parameter.type === 'float') && value) {
    const number = Number(value);
    if (!Number.isFinite(number) || (parameter.type === 'int' && !Number.isInteger(number))) return t(parameter.type === 'int' ? 'ct.param.integer' : 'ct.param.number', { label: parameter.label });
    if (parameter.minimum != null && number < parameter.minimum) return t('ct.param.minimum', { label: parameter.label, minimum: parameter.minimum });
    if (parameter.maximum != null && number > parameter.maximum) return t('ct.param.maximum', { label: parameter.label, maximum: parameter.maximum });
  }
  return control.checkValidity() ? null : (control.validationMessage || t('ct.param.invalid', { label: parameter.label }));
}
