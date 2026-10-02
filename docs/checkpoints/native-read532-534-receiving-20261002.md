# Native read and proof receiving checkpoint

This branch normally integrates merged Toad326 and pins merged Core532/533/534 at `457b1047855752f4d069ee1d39b01e30603efa41`. Current frontend remains qualified Toad326/Text26 until Toad325/Text27 supplies its scoped final source and receipt before package freeze. Full performance and S1/S4 are not release dependencies.

The normal lock resolves 99 packages; the existing production install recipe contains 69. No native rebuild: qualified manifest `00c2c11feaaf6e53b543d1570ae6029f8395e64ebafcdac54c352082cbc460c7`, tree `e0f93fec172aced120c0ce3e90345a27ece91ac2a0436bad3353169922dfecc7`, remains unchanged by Core534.

Source qualification remains separate: Core533 saved startup 2.317s, original context acquisition 27 body reads, count zero body reads and oversized context empty; Core534 scoped saved read 2.883 to 0.787s and 9757 to 205 decoded records with original proof hashes equal. These do not establish configured channel latency. Parent owns the actual configured channel and default publication.

One immutable normal installed target and existing preserve-only operator will be prepared after frontend scope freeze. Current326 prefix, rollback324, native ad533 and original/UNKNOWN input proofs remain immutable. No publication, owner restart, provider input or source migration is performed by this receiving branch.
