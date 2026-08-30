"""CPU qualification transition for targets that explicitly opt in."""


def _cpu_profile_impl(_settings, _attr):
    return {
        "//command_line_option:define": ["mindclade_accelerator=cpu"],
    }


cpu_profile_transition = transition(
    implementation = _cpu_profile_impl,
    inputs = [],
    outputs = ["//command_line_option:define"],
)
