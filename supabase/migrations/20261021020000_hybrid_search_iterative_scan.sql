-- hybrid_search: keep semantic recall when source_filter is set.
-- An HNSW scan returns at most hnsw.ef_search rows (default 40) and the product filter is applied
-- afterwards, so with source_filter = '{cli}' the semantic side could return nothing at all.
-- pgvector >= 0.8 iterative scans keep walking the graph until enough rows pass the filter.
-- relaxed_order is fine here: the sem CTE re-ranks its rows with row_number() over the distance.
-- ef_search 100 > the CTE's limit of 60, so unfiltered searches are not truncated either.
-- The hnsw.* parameters exist only once pgvector's library is loaded in this session; before that
-- they are placeholders the postgres role may not set (42501). Touching a vector value loads it.
select '[1]'::extensions.vector;

alter function tutor.hybrid_search(text, extensions.vector, integer, text[], integer)
  set hnsw.iterative_scan = 'relaxed_order'
  set hnsw.ef_search = 100;
