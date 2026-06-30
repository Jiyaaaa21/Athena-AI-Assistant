from backend.tools.base import BaseTool
from backend.rag.rag_pipeline import rag_answer


class RAGTool(BaseTool):

    @property
    def name(self):
        return "rag"

    @property
    def description(self):
        return "Answers questions using uploaded documents."

    def run(self, input_data):

        return rag_answer(input_data)