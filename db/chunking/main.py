from . import nyc_admin
from . import nys_sanitary
from . import nyc_health_code
from db import pinecone
from pathlib import Path

def main():
    pinecone.clear_index()

    root = Path(__file__).resolve().parent.parent.parent
    admin_code_dir = root / "data/scrapers/nyc-admin-code/data"
    admin_chunks = nyc_admin.get_chunks(admin_code_dir)
    pinecone.upload_chunks(admin_chunks)

    sanitary_code_dir = root / "data/scrapers/nys-sanitary-code/data"
    sanitary_chunks = nys_sanitary.get_chunks(sanitary_code_dir)
    pinecone.upload_chunks(sanitary_chunks)

    health_code_dir = root / "data/scrapers/nyc-health-code/data"
    health_code_chunks = nyc_health_code.get_chunks(health_code_dir)
    pinecone.upload_chunks(health_code_chunks)

if __name__ == "__main__":
    main()