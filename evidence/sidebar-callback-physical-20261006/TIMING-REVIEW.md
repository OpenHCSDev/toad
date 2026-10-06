# Physical05 motion and native timing review

The native records prove actual transcript wheel travel: 302→230 rows, 230→302, then 302→230. The right context panel moved 12→24 rows and returned to12. Selected screenshots confirm the visible context panel and retained transcript.

The three right-sidebar toggle handlers took1.50,3.90 and5.27ms. The next native writer completions followed in50.06,38.66 and69.45ms. These are handler/next-writer measurements, not input-to-photon latency or confirmation that every subsequent frame was smooth.

Across this recorded journey, layout duration median/p95 was14.49/26.05ms and maximum73.47ms; arrangement maximum96.39ms. Compositor refresh median/p95 was3.02/8.47ms. These distinguish the original owners doing work; they do not establish60FPS or a comparison against the prior live build.

**Left-sidebar scrolling remains unqualified.** Only two authored threads were present and fitted entirely. No overflowing roster was exercised. Passing the generic journey did not validate that path.

The full video presentation review and many-agents response burst remain open. The current public installation is unchanged. Exact original records, movement and limits are in[TIMING-REVIEW.json](TIMING-REVIEW.json).
