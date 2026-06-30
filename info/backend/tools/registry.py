from backend.tools.calculator import CalculatorTool
from backend.tools.rag_tool import RAGTool
from backend.tools.weather import WeatherTool
from backend.tools.news import NewsTool
from backend.tools.notes import NotesTool
from backend.tools.reminders import ReminderTool


tool_instances = [
    CalculatorTool(),
    RAGTool(),
    WeatherTool(),
    NewsTool(),
    NotesTool(),
    ReminderTool()
]

TOOLS = {
    tool.name: tool
    for tool in tool_instances
}