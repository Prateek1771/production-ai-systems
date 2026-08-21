from pathlib import Path

from app.ingestion.pipeline import IngestionPipeline


def test_ingest_documents():

    pipeline = IngestionPipeline()

    data_dir = Path(__file__).parents[2] / "data" / "raw"

    results = pipeline.process_directory(
        data_dir
    )

    assert results

    for document, chunks in results:

        print("\n")
        print("=" * 80)
        print("DOCUMENT:", document.filename)
        print("DOCUMENT ID:", document.document_id)
        print("CONTENT HASH:", document.content_hash)
        print("CHUNKS:", len(chunks))

        assert document.content
        assert chunks

        for chunk in chunks:

            print(
                f"\nChunk {chunk.chunk_index}"
            )

            print(
                f"ID: {chunk.chunk_id}"
            )

            print(
                f"Characters: {len(chunk.text)}"
            )

            print(
                chunk.text[:300]
            )

            assert chunk.document_id == document.document_id
            assert chunk.text
            assert chunk.chunk_id