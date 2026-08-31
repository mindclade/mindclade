# GENERATED FILE - DO NOT EDIT. Generator: kernels.native.codegen.generate@2.
from __future__ import annotations

_REGISTERED = False


def register_python_kernels() -> None:
    global _REGISTERED
    if _REGISTERED:
        return
    import torch
    from kernels.pairformer.outer_product_mean.tilelang import fake as _mindclade_fake_0
    torch.library.register_fake('mindclade::outer_product_mean')(_mindclade_fake_0)
    from kernels.pairformer.outer_product_mean.tilelang import setup_context as _mindclade_setup_context_0
    from kernels.pairformer.outer_product_mean.tilelang import backward as _mindclade_backward_0
    torch.library.register_autograd('mindclade::outer_product_mean', _mindclade_backward_0, setup_context=_mindclade_setup_context_0)
    from kernels.pairformer.pair_weighted_average.tilelang import fake as _mindclade_fake_1
    torch.library.register_fake('mindclade::pair_weighted_average')(_mindclade_fake_1)
    from kernels.pairformer.pair_weighted_average.tilelang import setup_context as _mindclade_setup_context_1
    from kernels.pairformer.pair_weighted_average.tilelang import backward as _mindclade_backward_1
    torch.library.register_autograd('mindclade::pair_weighted_average', _mindclade_backward_1, setup_context=_mindclade_setup_context_1)
    from kernels.pairformer.transition.tilelang import fake as _mindclade_fake_2
    torch.library.register_fake('mindclade::transition')(_mindclade_fake_2)
    from kernels.pairformer.transition.tilelang import setup_context as _mindclade_setup_context_2
    from kernels.pairformer.transition.tilelang import backward as _mindclade_backward_2
    torch.library.register_autograd('mindclade::transition', _mindclade_backward_2, setup_context=_mindclade_setup_context_2)
    from kernels.pairformer.triangle_attention.tilelang import fake as _mindclade_fake_3
    torch.library.register_fake('mindclade::triangle_attention')(_mindclade_fake_3)
    from kernels.pairformer.triangle_attention.tilelang import setup_context as _mindclade_setup_context_3
    from kernels.pairformer.triangle_attention.tilelang import backward as _mindclade_backward_3
    torch.library.register_autograd('mindclade::triangle_attention', _mindclade_backward_3, setup_context=_mindclade_setup_context_3)
    from kernels.pairformer.triangle_multiplication.tilelang import fake as _mindclade_fake_4
    torch.library.register_fake('mindclade::triangle_multiplication')(_mindclade_fake_4)
    from kernels.pairformer.triangle_multiplication.tilelang import setup_context as _mindclade_setup_context_4
    from kernels.pairformer.triangle_multiplication.tilelang import backward as _mindclade_backward_4
    torch.library.register_autograd('mindclade::triangle_multiplication', _mindclade_backward_4, setup_context=_mindclade_setup_context_4)
    _REGISTERED = True
