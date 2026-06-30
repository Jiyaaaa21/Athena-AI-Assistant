from backend.tools.base import BaseTool


class CalculatorTool(BaseTool):

    @property
    def name(self):
        return "calculator"

    @property
    def description(self):
        return "Performs mathematical calculations."

    def run(self, input_data):

        try:
            result = eval(input_data)
            return str(result)

        except Exception as e:
            return f"Error: {e}"