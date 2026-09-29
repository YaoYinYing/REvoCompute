const resultPath = /^\/compute\/results\/([0-9a-f]{32})\/?$/i;

export const resultTaskId = (pathname: string): string | null => {
  const match = resultPath.exec(pathname);
  return match?.[1]?.toLowerCase() || null;
};
