/**
 * LeftNav — Server Component
 * spec.md §2 Navigation: width 180px, position absolute left 0,
 * text-align right (Supreme asymmetric right-edge tension).
 *
 * Items must be uppercase, Inter-Bold, 13px, line-height 1.8.
 * Hover/active colour: #FF0000 (brand red, instantaneous — no transition).
 */

interface LeftNavProps {
  activeId?: string;
}

const NAV_ITEMS = [
  { label: "WORK",    href: "#work"    },
  { label: "INFO",    href: "#info"    },
  { label: "CONTACT", href: "#contact" },
  { label: "CV",      href: "/cv.pdf"  },
];

export default function LeftNav({ activeId }: LeftNavProps) {
  return (
    <nav
      className="supreme-nav"
      aria-label="Primary navigation"
    >
      {NAV_ITEMS.map((item) => (
        <a
          key={item.label}
          href={item.href}
          className={activeId === item.label.toLowerCase() ? "active" : ""}
        >
          {item.label}
        </a>
      ))}
    </nav>
  );
}
