"""GPU qualification transition for targets activated by reviewed evidence."""

def _gpu_profile_impl(_settings, attr):
    if not attr.gpu_envelope:
        fail("gpu_envelope is required for a GPU transition")
    return {
        "//command_line_option:define": [
            "mindclade_accelerator=gpu",
            "mindclade_gpu_envelope=%s" % attr.gpu_envelope,
        ],
    }

gpu_profile_transition = transition(
    implementation = _gpu_profile_impl,
    inputs = [],
    outputs = ["//command_line_option:define"],
)
