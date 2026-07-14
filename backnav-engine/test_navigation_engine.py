from focus_target import FocusTarget
from navigation_engine import NavigationEngine

engine = NavigationEngine()

engine.record(FocusTarget("1", "org.kde.kate", "architecture.md"))
engine.record(FocusTarget("2", "org.kde.konsole", "journalctl"))
engine.record(FocusTarget("3", "brave-browser", "GitHub"))

print("Initial")
engine.dump()

print("\nBack")
print(engine.back())

print("\nBack")
print(engine.back())

print("\nForward")
print(engine.forward())

print("\nFinal")
engine.dump()
