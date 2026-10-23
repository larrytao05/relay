function BrandMark() {
  return (
    <span className="brand-mark" aria-hidden="true">
      <svg viewBox="0 0 20 20" fill="none">
        <path
          d="M4 5.5h7.5a3 3 0 0 1 0 6H8.5a3 3 0 0 0 0 6H16"
          stroke="currentColor"
          strokeWidth="2"
          strokeLinecap="round"
        />
        <circle cx="4" cy="5.5" r="1.5" fill="currentColor" />
        <circle cx="16" cy="17.5" r="1.5" fill="currentColor" />
      </svg>
    </span>
  );
}

export default function Brand() {
  return (
    <div className="brand">
      <BrandMark />
      <span>relay</span>
    </div>
  );
}
