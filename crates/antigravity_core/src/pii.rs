//! pii — Zero-Copy PII Detection Engine (Phase 3)
//!
//! Detects Personally Identifiable Information in a borrowed `&str` view of
//! the `Arc<[u8]>` payload.  The underlying bytes are NEVER copied or mutated;
//! only offset metadata is collected.
//!
//! Architecture
//! ------------
//! All `Regex` objects are compiled ONCE at process startup via a static
//! `OnceLock<PiiDetector>`.  After initialisation, every call to `detector()`
//! is a single pointer dereference — no allocation, no locking on the hot path.
//!
//! `Regex` implements `Send + Sync` (its DFA/NFA state machine is read-only
//! at runtime), so the `OnceLock` can be safely shared across Tokio threads.
//!
//! Zero-Copy Guarantee
//! -------------------
//!   Input:   `&str` — a borrowed view into Arc's heap allocation
//!   Scan:    `Regex::find_iter` traverses the `&str` without allocating
//!   Output:  `Vec<PiiMatch>` — only byte-offset metadata is collected
//!
//! The `Vec` and JSON serialisation are the only allocations Phase 3 adds.

use std::sync::OnceLock;

use regex::Regex;
use serde::Serialize;

// ── PII entity type ────────────────────────────────────────────────────────────

/// Categorised PII entity type.
///
/// Serialised as SCREAMING_SNAKE_CASE so Python callers can use string matching:
///   `assert m['pii_type'] == 'CREDIT_CARD'`
#[derive(Debug, Clone, Copy, Serialize)]
#[serde(rename_all = "SCREAMING_SNAKE_CASE")]
pub enum PiiKind {
    Email,
    CreditCard,
    Ssn,
}

// ── Bounding box result ────────────────────────────────────────────────────────

/// A single PII match: entity type and byte offsets in the input `&str`.
///
/// Byte offsets — not Unicode codepoint offsets — to align with Python's
/// `bytes` indexing convention: `payload[match.start:match.end]`.
///
/// `start` is the index of the first byte of the match.
/// `end` is one past the last byte (exclusive, Python slice convention).
#[derive(Debug, Serialize)]
pub struct PiiMatch {
    pub pii_type: PiiKind,
    pub start:    usize,
    pub end:      usize,
}

// ── Compiled detector ──────────────────────────────────────────────────────────

/// Stateless PII detector holding pre-compiled regex patterns.
///
/// `Regex` is `Send + Sync`; `Vec` is `Send + Sync` when its elements are.
/// Therefore `PiiDetector` is `Send + Sync` and safe to store in a `OnceLock`.
pub struct PiiDetector {
    patterns: Vec<(PiiKind, Regex)>,
}

// SAFETY: Regex is Send + Sync (its DFA/NFA is read-only after compilation).
unsafe impl Send for PiiDetector {}
unsafe impl Sync for PiiDetector {}

impl PiiDetector {
    fn new() -> Self {
        Self {
            patterns: vec![
                // Email addresses — RFC 5321 simplified form.
                // Matches: user.name+tag@sub.domain.co
                // Does NOT match: quoted local-parts or IP-literal domains
                // (acceptable for HFT gateway PII detection use case).
                (
                    PiiKind::Email,
                    Regex::new(r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b")
                        .expect("EMAIL regex failed to compile"),
                ),
                // Credit card numbers — 16-digit groups separated by optional
                // spaces or hyphens.  Matches common Visa/MC/Amex/Discover
                // formatted strings.  Does not perform Luhn validation
                // (validation is correct responsibility of downstream systems).
                (
                    PiiKind::CreditCard,
                    Regex::new(r"\b\d{4}[\s\-]?\d{4}[\s\-]?\d{4}[\s\-]?\d{4}\b")
                        .expect("CREDIT_CARD regex failed to compile"),
                ),
                // US Social Security Numbers — canonical ddd-dd-dddd format.
                // Does NOT match unformatted 9-digit runs to avoid false positives
                // (e.g. timestamps, phone numbers).
                (
                    PiiKind::Ssn,
                    Regex::new(r"\b\d{3}-\d{2}-\d{4}\b")
                        .expect("SSN regex failed to compile"),
                ),
            ],
        }
    }

    /// Scan `text` for PII and return all bounding boxes sorted by `start`.
    ///
    /// The scan is read-only: `find_iter` borrows `text` without allocating.
    /// The returned `Vec<PiiMatch>` holds only numeric offsets — no byte copies.
    pub fn detect(&self, text: &str) -> Vec<PiiMatch> {
        let mut matches: Vec<PiiMatch> = self
            .patterns
            .iter()
            .flat_map(|(kind, re)| {
                re.find_iter(text).map(move |m| PiiMatch {
                    pii_type: *kind,
                    start:    m.start(),
                    end:      m.end(),
                })
            })
            .collect();

        // Sort by start offset so the Python caller receives matches in
        // document order regardless of which pattern triggered first.
        matches.sort_unstable_by_key(|m| m.start);
        matches
    }
}

// ── Process-wide singleton ─────────────────────────────────────────────────────

/// `OnceLock` ensures exactly-once initialisation across all Python threads.
/// After the first call, `get_or_init` returns instantly (single atomic load).
static PII_DETECTOR: OnceLock<PiiDetector> = OnceLock::new();

/// Return the process-wide compiled `PiiDetector`.
///
/// First call: compiles all regex patterns (tens of microseconds).
/// Subsequent calls: single pointer dereference, no synchronisation overhead.
pub fn detector() -> &'static PiiDetector {
    PII_DETECTOR.get_or_init(PiiDetector::new)
}
