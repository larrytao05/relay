export function isRevisionGap(currentRevision: number, incomingRevision: number): boolean {
  return incomingRevision > currentRevision + 1;
}

export function shouldRetrySocketClose(code: number): boolean {
  return code !== 1008 && code !== 4002;
}
