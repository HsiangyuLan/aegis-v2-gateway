//! Compiled-regex PII detector: read-only scan over borrowed UTF-8.

use ag_types::{PiiKind, PiiMatch};
use once_cell::sync::Lazy;
use regex::Regex;

/// Stateless detector holding pre-compiled patterns.
pub struct PiiRegexDetector {
    patterns: Vec<(PiiKind, Regex)>,
}

impl PiiRegexDetector {
    pub fn new() -> Self {
        Self {
            patterns: vec![
                (
                    PiiKind::Email,
                    Regex::new(r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b")
                        .expect("EMAIL regex"),
                ),
                (
                    PiiKind::CreditCard,
                    Regex::new(r"\b\d{4}[\s\-]?\d{4}[\s\-]?\d{4}[\s\-]?\d{4}\b")
                        .expect("CC regex"),
                ),
                (
                    PiiKind::Ssn,
                    Regex::new(r"\b\d{3}-\d{2}-\d{4}\b").expect("SSN regex"),
                ),
            ],
        }
    }

    /// Scan `text` for PII; returns byte offsets sorted by start.
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
        matches.sort_unstable_by_key(|m| m.start);
        matches
    }
}

impl Default for PiiRegexDetector {
    fn default() -> Self {
        Self::new()
    }
}

static DETECTOR: Lazy<PiiRegexDetector> = Lazy::new(PiiRegexDetector::new);

/// Process-wide singleton detector.
pub fn detector() -> &'static PiiRegexDetector {
    &DETECTOR
}
