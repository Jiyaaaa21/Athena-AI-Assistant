from backend.tools.notes import NotesTool

tool = NotesTool()

print(
    tool.run(
        "save: Interview on Friday"
    )
)

print()

print(
    tool.run(
        "save: Complete Athena frontend"
    )
)

print()

print(
    tool.run(
        "list"
    )
)