from backend.tools.weather import WeatherTool

tool = WeatherTool()

print(
    tool.run("Delhi")
)