import chunking.nyc_admin
import chunking.nys_sanitary
import chunking.nyc_health_code
import pinecone
from pathlib import Path

def main():
    pinecone.clear_index()

    root = Path(__file__).resolve().parent.parent
    admin_code_dir = root / "scraping/nyc-admin-code/data"
    admin_chunks = chunking.nyc_admin.get_chunks(admin_code_dir)
    pinecone.upload_chunks(admin_chunks)

    sanitary_code_dir = root / "scraping/nys-sanitary-code/data"
    sanitary_chunks = chunking.nys_sanitary.get_chunks(sanitary_code_dir)
    pinecone.upload_chunks(sanitary_chunks)

    health_code_dir = root / "scraping/nyc-health-code/data"
    health_code_chunks = chunking.nyc_health_code.get_chunks(health_code_dir)
    pinecone.upload_chunks(health_code_chunks)

if __name__ == "__main__":
    main()