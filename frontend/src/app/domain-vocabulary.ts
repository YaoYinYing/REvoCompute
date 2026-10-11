import type { AcademicPosition, AdminLogName, GrantBasis } from '../api/contracts';

function entries<Key extends string>(labels: Record<Key, string>): Array<[Key, string]> {
  return Object.entries(labels) as Array<[Key, string]>;
}

export const academicPositionLabels = {
  undergraduate_student: 'Undergraduate student',
  masters_student: "Master's student",
  phd_student: 'PhD student',
  postdoctoral_researcher: 'Postdoctoral researcher',
  research_assistant: 'Research assistant',
  lecturer: 'Lecturer',
  assistant_professor: 'Assistant professor',
  associate_professor: 'Associate professor',
  professor: 'Professor',
  industry_researcher: 'Industry researcher',
  other: 'Other',
} satisfies Record<AcademicPosition, string>;

export const grantBasisLabels = {
  lab_member: 'Lab member',
  institutional_collaborator: 'Institutional collaborator',
  individually_verified: 'Individually verified',
  other: 'Other',
} satisfies Record<GrantBasis, string>;

export const adminLogLabels = {
  'gunicorn-access': 'Gunicorn access',
  'gunicorn-error': 'Gunicorn error',
  'celery-worker': 'Celery worker',
  'operational-events': 'Operational events',
  maintenance: 'Maintenance',
} satisfies Record<AdminLogName, string>;

export const academicPositionOptions = entries<AcademicPosition>(academicPositionLabels);
export const grantBasisOptions = entries<GrantBasis>(grantBasisLabels);
export const adminLogOptions = entries<AdminLogName>(adminLogLabels);

/** Read one string field of a server-projected sub-object, or nothing. */
export function metadataValue(value: unknown, key: string): string | null {
  if (!value || typeof value !== 'object') return null;
  const item = (value as Record<string, unknown>)[key]; return typeof item === 'string' && item ? item : null;
}

/** Resolve a server-supplied URL, admitting only http(s) as a real destination. */
export function safeExternalUrl(value: string | null): string | null {
  if (!value) return null;
  try { const url = new URL(value, location.origin); return url.protocol === 'http:' || url.protocol === 'https:' ? url.href : null; }
  catch { return null; }
}
