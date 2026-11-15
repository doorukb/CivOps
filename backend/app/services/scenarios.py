# Scripted fictional calls: id -> (title, [(seconds_before_segment, text), ...]).
# Replayed as final TranscriptEvents so the demo needs no microphone or Deepgram.
SCENARIOS = {
    "routine_wellbeing": (
        "Routine wellbeing check",
        [
            (1.0, "Hi, I'm calling about my neighbor, an older man who lives alone."),
            (3.0, "I haven't seen him come out for his mail in three days."),
            (3.0, "No, nobody is hurt that I know of, and there are no weapons."),
            (3.0, "I just want someone to knock on his door and check on him."),
        ],
    ),
    "hidden_knife": (
        "Noise dispute, then a knife",
        [
            (1.0, "My upstairs neighbors are being really loud again."),
            (3.0, "They keep shouting at each other and slamming doors."),
            (3.0, "Wait, I just saw the guy holding a knife in the hallway."),
        ],
    ),
    "incomplete_screening": (
        "Argument with unknown safety details",
        [
            (1.0, "Two people are arguing loudly outside my building."),
            (3.0, "I can't tell if it's going to turn physical."),
        ],
    ),
}
