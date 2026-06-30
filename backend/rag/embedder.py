from sentence_transformers import SentenceTransformer

model = SentenceTransformer(
    "all-MiniLM-L6-v2"
)


def create_embeddings(chunks):

    embeddings = model.encode(
        chunks,
        convert_to_numpy=True
    )

    return embeddings

def create_query_embedding(query):

    embedding = model.encode(
        query,
        convert_to_numpy=True
    )

    return embedding