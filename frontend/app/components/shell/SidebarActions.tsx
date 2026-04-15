"use client";

/**
 * SidebarActions — Client Component
 * Contains interactive buttons at the bottom of the Sidebar.
 * Isolated as a CC so the Sidebar parent can remain a pure SC.
 */
export default function SidebarActions() {
  return (
    <div className="mt-auto border-t border-white/5 p-4 flex flex-col gap-2">
      <button
        className="bg-primary-container text-on-primary font-bold py-3 px-4 uppercase text-xs tracking-widest active:scale-[0.98] border-0"
        style={{ fontFamily: "var(--font-headline)" }}
        onClick={() => {
          // EXECUTE_SEQUENCE: future FastAPI call
          console.info("[AEGIS] EXECUTE_SEQUENCE triggered");
        }}
      >
        EXECUTE_SEQUENCE
      </button>

      <div className="flex gap-2 mt-2">
        <button
          className="flex-1 flex items-center justify-center gap-2 py-2 text-stone-500 secondary-label text-[10px] tracking-widest font-bold uppercase hover:text-error specular-highlights"
          style={{ fontFamily: "var(--font-headline)" }}
          onClick={() => console.info("[AEGIS] REBOOT requested")}
        >
          <span className="material-symbols-outlined text-sm">power_settings_new</span>
          REBOOT
        </button>
        <button
          className="flex-1 flex items-center justify-center gap-2 py-2 text-stone-500 secondary-label text-[10px] tracking-widest font-bold uppercase hover:text-white specular-highlights"
          style={{ fontFamily: "var(--font-headline)" }}
          onClick={() => console.info("[AEGIS] EXIT requested")}
        >
          <span className="material-symbols-outlined text-sm">logout</span>
          EXIT
        </button>
      </div>
    </div>
  );
}
