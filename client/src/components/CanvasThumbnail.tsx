import type { CanvasPreviewKind } from "../types.ts";

export default function CanvasThumbnail({ kind }: { kind: CanvasPreviewKind }) {
  switch (kind) {
    case "checkout":
      return (
        <svg viewBox="0 0 50 30" fill="none" aria-hidden="true">
          <rect x="2" y="9" width="14" height="12" rx="3" fill="#edf1ff" stroke="#c9d5fa" />
          <rect x="19" y="9" width="15" height="12" rx="3" fill="#f6e8bd" stroke="#e7d390" />
          <ellipse cx="42" cy="15" rx="6" ry="5.5" fill="#d9eee4" stroke="#b6ddca" />
          <path d="M16 15h3m15 0h5" stroke="#8290a0" />
        </svg>
      );
    case "account":
      return (
        <svg viewBox="0 0 50 30" fill="none" aria-hidden="true">
          <rect x="2" y="8" width="13" height="14" rx="3" fill="#d9eee4" stroke="#b6ddca" />
          <rect x="18" y="8" width="14" height="14" rx="3" fill="#edf1ff" stroke="#c9d5fa" />
          <rect x="35" y="8" width="13" height="14" rx="6" fill="#f2dfe0" stroke="#e5c9cc" />
        </svg>
      );
    case "planning":
      return (
        <svg viewBox="0 0 50 30" fill="none" aria-hidden="true">
          <rect x="2" y="3" width="13" height="8" rx="2" fill="#f6e8bd" />
          <rect x="18" y="3" width="13" height="8" rx="2" fill="#d9eee4" />
          <rect x="34" y="3" width="14" height="8" rx="2" fill="#edf1ff" />
          <path d="M8 12v7h17m-1-7v7m0 0h9" stroke="#8e9aa8" />
          <rect x="18" y="19" width="14" height="7" rx="2" fill="#fff" stroke="#dce2e8" />
        </svg>
      );
    default: {
      const exhaustiveCheck: never = kind;
      return exhaustiveCheck;
    }
  }
}
