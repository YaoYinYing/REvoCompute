import type { components, operations } from './schema.generated';

export type AcademicPosition = components['schemas']['RegisterRequest']['position'];
export type GrantBasis = components['schemas']['EntitlementGrantRequest']['basis'];
export type AdminLogName = operations['getAdminLogTail']['parameters']['path']['log_name'];
