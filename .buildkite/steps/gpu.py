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
            command=(
                "nix develop --no-accept-flake-config --no-update-lock-file "
                ".#deepep --command just ci-gpu"
            ),
            timeout_minutes=240,
            depends_on=("gpu-activation-gate",),
            artifact_paths=("build/evidence/gpu-deepep-intranode.json",),
        ),
        Step(
            key="pairformer-sm90a-qualification-preflight",
            label=":gpu: Pairformer SM90a qualification preflight",
            command=(
                "nix develop --command python3.12 -m "
                "kernels.native.python.gpu_qualification "
                "--plan kernels/native/manifests/pairformer_gpu_qualification.json "
                "--lane sm90a --verify-environment "
                "--output build/evidence/pairformer-sm90a-preflight.json"
            ),
            timeout_minutes=30,
            depends_on=("gpu-activation-gate",),
            artifact_paths=("build/evidence/pairformer-sm90a-preflight.json",),
            agent_tags={"gpu_arch": "sm90a"},
        ),
        Step(
            key="pairformer-sm100a-qualification-preflight",
            label=":gpu: Pairformer SM100a independent qualification preflight",
            command=(
                "nix develop --command python3.12 -m "
                "kernels.native.python.gpu_qualification "
                "--plan kernels/native/manifests/pairformer_gpu_qualification.json "
                "--lane sm100a --verify-environment "
                "--output build/evidence/pairformer-sm100a-preflight.json"
            ),
            timeout_minutes=30,
            depends_on=("gpu-activation-gate",),
            artifact_paths=("build/evidence/pairformer-sm100a-preflight.json",),
            agent_tags={"gpu_arch": "sm100a"},
        ),
        Step(
            key="gpu-multinode-probe",
            label=":network: DeepEP protected multi-node RDMA probe",
            command=(
                "MINDCLADE_DEEPEP_NODE_RANK=${BUILDKITE_PARALLEL_JOB} "
                "MINDCLADE_DEEPEP_RDZV_ID=${BUILDKITE_BUILD_ID} "
                "nix develop --no-accept-flake-config --no-update-lock-file "
                ".#deepep --command just ci-gpu-multinode"
            ),
            timeout_minutes=240,
            depends_on=("gpu-activation-gate",),
            artifact_paths=("build/evidence/gpu-deepep-multinode-node-*.json",),
            env={"MINDCLADE_DEEPEP_NNODES": "2"},
            parallelism=2,
        ),
    ]
