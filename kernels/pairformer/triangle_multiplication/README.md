# Triangle Multiplication

The operation consumes `left` and `right` tensors shaped `[..., N, N, C]` and
a boolean or floating mask shaped `[..., N, N]`. It returns `[..., N, N, C]`.

Outgoing mode contracts `left[..., i, k, c]` with
`right[..., j, k, c]`. Incoming mode contracts `left[..., k, i, c]` with
`right[..., k, j, c]`. Both operands and the result are masked. TileLang
profiles accumulate in FP32 and specialize the direction at build time.

The only dispatcher identity is
`torch.ops.mindclade.triangle_multiplication`.
