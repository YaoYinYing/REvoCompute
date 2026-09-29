import type { ParameterDefinition } from './types';

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
  if (parameter.required && !value) return `${parameter.label} is required.`;
  if (parameter.choices.length && !parameter.choices.some(choice => String(choice) === value)) return `Choose a listed ${parameter.label.toLowerCase()} value.`;
  if ((parameter.type === 'int' || parameter.type === 'float') && value) {
    const number = Number(value);
    if (!Number.isFinite(number) || (parameter.type === 'int' && !Number.isInteger(number))) return `${parameter.label} must be a valid ${parameter.type === 'int' ? 'integer' : 'number'}.`;
    if (parameter.minimum != null && number < parameter.minimum) return `${parameter.label} must be at least ${parameter.minimum}.`;
    if (parameter.maximum != null && number > parameter.maximum) return `${parameter.label} must be at most ${parameter.maximum}.`;
  }
  return control.checkValidity() ? null : (control.validationMessage || `${parameter.label} is invalid.`);
}
