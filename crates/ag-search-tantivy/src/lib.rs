//! Tantivy-backed search with shared `IndexReader` and NRT reload.

use std::fs;
use std::path::Path;
use std::sync::{Arc, RwLock};

use ag_error::AgError;
use ag_types::{SearchHit, SearchResponse};
use tantivy::collector::TopDocs;
use tantivy::query::QueryParser;
use tantivy::schema::*;
use tantivy::{doc, Index, IndexReader, ReloadPolicy, TantivyDocument};
use tracing::info;

const DEFAULT_DOCS: &[(&str, &str)] = &[
    ("Antigravity", "Sovereign Core zero-copy FFI gateway"),
    ("FinOps", "Cache hit 80 percent Rust speedup arbitrage"),
    ("Visa", "H1B tariff exemption narrative portfolio KPI"),
];

/// Thread-safe search service.
pub struct SearchEngine {
    index:  Arc<Index>,
    reader: Arc<RwLock<IndexReader>>,
    title:  Field,
    body:   Field,
}

impl SearchEngine {
    /// Open or create index at `dir`; seeds demo documents if empty.
    pub fn open_or_create(dir: &Path) -> Result<Self, AgError> {
        if let Some(parent) = dir.parent() {
            let _ = fs::create_dir_all(parent);
        }
        let _ = fs::create_dir_all(dir);

        let mut schema_builder = Schema::builder();
        let title = schema_builder.add_text_field("title", TEXT | STORED);
        let body = schema_builder.add_text_field("body", TEXT | STORED);
        let schema = schema_builder.build();

        let index = Index::open_in_dir(dir).or_else(|_| {
            Index::create_in_dir(dir, schema.clone()).map_err(|e| AgError::Search(e.to_string()))
        })?;
        let index = Arc::new(index);

        let reader: IndexReader = index
            .reader_builder()
            .reload_policy(ReloadPolicy::OnCommitWithDelay)
            .try_into()
            .map_err(|e| AgError::Search(e.to_string()))?;

        let reader = Arc::new(RwLock::new(reader));

        let need_seed = reader
            .read()
            .map_err(|e| AgError::Search(e.to_string()))?
            .searcher()
            .num_docs()
            == 0;

        if need_seed {
            // Tantivy 0.26+ requires heap ≥ 15_000_000 bytes per writer thread.
            let mut writer: tantivy::IndexWriter = index.writer(16 * 1024 * 1024).map_err(|e| {
                AgError::Search(e.to_string())
            })?;
            for (t, b) in DEFAULT_DOCS {
                writer
                    .add_document(doc!(
                        title => *t,
                        body => *b,
                    ))
                    .map_err(|e| AgError::Search(e.to_string()))?;
            }
            writer.commit().map_err(|e| AgError::Search(e.to_string()))?;
            reader
                .write()
                .map_err(|e| AgError::Search(e.to_string()))?
                .reload()
                .map_err(|e| AgError::Search(e.to_string()))?;
            info!("Tantivy: seeded {} demo documents", DEFAULT_DOCS.len());
        }

        Ok(Self {
            index,
            reader,
            title,
            body,
        })
    }

    /// Run query over `title` and `body`; returns top-k hits.
    pub fn search(&self, q: &str, limit: usize) -> Result<SearchResponse, AgError> {
        let started = std::time::Instant::now();
        if q.trim().is_empty() {
            return Ok(SearchResponse {
                hits:    vec![],
                took_ms: started.elapsed().as_secs_f64() * 1000.0,
            });
        }

        let reader = self
            .reader
            .read()
            .map_err(|e| AgError::Search(e.to_string()))?;
        let searcher = reader.searcher();

        let qp = QueryParser::for_index(&self.index, vec![self.title, self.body]);
        let query = qp
            .parse_query(q)
            .map_err(|e| AgError::Search(e.to_string()))?;

        let lim = limit.max(1).min(50);
        let collector = TopDocs::with_limit(lim).order_by_score();
        let top_docs = searcher
            .search(&query, &collector)
            .map_err(|e| AgError::Search(e.to_string()))?;

        let mut hits: Vec<SearchHit> = Vec::with_capacity(top_docs.len());
        for (score, doc_address) in top_docs {
            let doc: TantivyDocument = searcher
                .doc(doc_address)
                .map_err(|e| AgError::Search(e.to_string()))?;
            let title = doc
                .get_first(self.title)
                .and_then(|v| v.as_str())
                .unwrap_or("")
                .to_string();
            let body_full = doc
                .get_first(self.body)
                .and_then(|v| v.as_str())
                .unwrap_or("");
            let snippet = body_full.chars().take(120).collect::<String>();
            let id = u64::from(doc_address.segment_ord) << 32 | u64::from(doc_address.doc_id);
            hits.push(SearchHit {
                id,
                title,
                snippet,
                score,
            });
        }

        Ok(SearchResponse {
            hits,
            took_ms: started.elapsed().as_secs_f64() * 1000.0,
        })
    }
}
