//! Zero-copy payload ownership: one `Arc<[u8]>` allocation after FFI boundary.

use std::sync::Arc;

use ag_error::AgError;

/// Validate UTF-8 then transfer ownership into `Arc<[u8]>`.
#[inline]
pub fn arc_from_utf8_bytes(bytes: &[u8]) -> Result<Arc<[u8]>, AgError> {
    std::str::from_utf8(bytes)?;
    Ok(Arc::from(bytes))
}

/// Borrow `&str` from `Arc<[u8]>` after UTF-8 was validated at allocation time.
///
/// # Safety
/// Call only when `arc_from_utf8_bytes` (or equivalent validation) was used for these bytes.
#[inline]
pub unsafe fn str_from_arc_unchecked(arc: &Arc<[u8]>) -> &str {
    // SAFETY: UTF-8 invariant established at `arc_from_utf8_bytes`.
    std::str::from_utf8_unchecked(arc)
}
