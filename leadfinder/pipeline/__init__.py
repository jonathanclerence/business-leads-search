"""Sales pipeline: clean scraped leads, publish preview websites to
dunous.com/previewsite/<slug>, and track every lead from "new" to "live".

    python -m pipeline import     # batches/*/leads.csv → clean list + tracker
    python -m pipeline enrich     # real opening hours + review quotes for the next leads
    python -m pipeline publish    # build previews → marketing-site → push
    python -m pipeline verify     # mark previews that are live as hosted
    python -m pipeline coverage   # which towns × business types are done
    python -m pipeline export-site <slug>   # finished site for the client

The tracker UI is served by the main app at http://localhost:5000/pipeline.
"""
