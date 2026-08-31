"""Activation-gated GPU qualification pipeline."""

from __future__ import annotations

from pipeline_model import Step


def steps() -> list[Step]:
    return [
        Step(
            key="gpu-activation-gate",
            label=":no_entry: Verify GPU activation evidence",
            command="just require-activation gpu",
            timeout_minutes=10,
        ),
        Step(
            key="gpu-intranode-probe",
            label=":gpu: DeepEP intra-node GPU probe",
            command="just ci-gpu",
            timeout_minutes=240,
            depends_on=("gpu-activation-gate",),
            artifact_paths=("build/evidence/gpu-deepep-intranode.json",),
        ),
        Step(
            key="gpu-multinode-probe",
            label=":network: DeepEP protected multi-node RDMA probe",
            command=(
                "MINDCLADE_DEEPEP_NODE_RANK=${BUILDKITE_PARALLEL_JOB} "
                "MINDCLADE_DEEPEP_RDZV_ID=${BUILDKITE_BUILD_ID} just ci-gpu-multinode"
            ),
            timeout_minutes=240,
            depends_on=("gpu-activation-gate",),
            artifact_paths=("build/evidence/gpu-deepep-multinode-node-*.json",),
            env={"MINDCLADE_DEEPEP_NNODES": "2"},
            parallelism=2,
        ),
    ]
