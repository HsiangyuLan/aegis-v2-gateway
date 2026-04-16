//! Merge overlapping PII spans and apply `[REDACTED]` masks.

use ag_types::PiiMatch;

/// Merge overlapping / adjacent spans (by byte range).
pub fn merge_spans(mut spans: Vec<PiiMatch>) -> Vec<PiiMatch> {
    if spans.is_empty() {
        return spans;
    }
    spans.sort_unstable_by_key(|m| (m.start, m.end));
    let mut merged: Vec<PiiMatch> = Vec::with_capacity(spans.len());
    let mut cur = spans[0].clone();
    for m in spans.into_iter().skip(1) {
        if m.start <= cur.end {
            cur.end = cur.end.max(m.end);
        } else {
            merged.push(cur);
            cur = m;
        }
    }
    merged.push(cur);
    merged
}

/// Replace each span with `[REDACTED]` (allocates new `String`).
pub fn redact_text(text: &str, spans: &[PiiMatch]) -> String {
    let spans = merge_spans(spans.to_vec());
    if spans.is_empty() {
        return text.to_string();
    }
    let mut out = String::with_capacity(text.len());
    let mut last = 0usize;
    for m in &spans {
        if m.start > last {
            out.push_str(&text[last..m.start.min(text.len())]);
        }
        out.push_str("[REDACTED]");
        last = m.end.min(text.len());
    }
    if last < text.len() {
        out.push_str(&text[last..]);
    }
    out
}

#[cfg(test)]
mod tests {
    use super::*;
    use ag_types::PiiKind;

    #[test]
    fn redact_email() {
        let t = "mail alice@x.com end";
        let spans = vec![PiiMatch {
            pii_type: PiiKind::Email,
            start:    5,
            end:      17,
        }];
        let r = redact_text(t, &spans);
        assert_eq!(r, "mail [REDACTED] end");
    }
}
