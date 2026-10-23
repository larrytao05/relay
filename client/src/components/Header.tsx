import type { ReactNode } from "react";
import "./Header.css";

type HeaderProps = {
  children: ReactNode;
  className?: string;
};

export default function Header({ children, className = "" }: HeaderProps) {
  return <header className={`page-header ${className}`.trim()}>{children}</header>;
}
