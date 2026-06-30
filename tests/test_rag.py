from backend.rag.rag_pipeline import rag_answer

question = "What projects has Jyoti worked on?"

answer = rag_answer(question)

print(answer)