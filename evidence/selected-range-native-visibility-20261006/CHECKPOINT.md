# Selected range: native visibility owner

## Change

The two existing helper consumers, select_rows and selected_target_actions, now derive all five visibility observations from Screen's existing Compositor.visible_widgets. The original compositor supplies positive clipped paint rectangles. No local region calculation, visibility wrapper, renderer override, backend patch or alternate predicate was added.

Widget.is_on_screen calls Screen.find_widget and Compositor.find_widget. That geometry lookup can return retained/full-map geometry for a clipped row; membership does not prove a positive painted rectangle. The helper's clipped-range assertion requires precisely that latter fact. Existing throbber and reader consumers already use the native paint cohort for the same question. Pattern IDEN-7: the old check answers a wider geometry-membership question than visible clipping.

The original off-screen anchor/visible endpoint requirement remains. Native Shift still must select all60 admitted rows in original hierarchy order, preserve the selected mode and complete all later native owner/batch checks. No status exemption, forced scroll/focus, deadline increase or changed production selection logic.

## Source verification

Original Package parsed288 Toad production +403 tests +40 tools +249 selected native modules with zero omissions. BEFORE.json records all visibility consumers and exact selected native owners. AFTER.json records both changed helper consumers, all other declarations ASTequal and all123 other assertions ASTequal. Seven sibling helpers are byteequal main; one changed module compiles without imports. Diff check passes.

## Retained actual result

Batch08 soleApp failed after56.916971s; operator joined57.969838s. The earlier selection, mixed read/pin, partial-failure and exact-tag survivor assertions completed before the clipped-range setup assertion at declared_target_actions_installed_pilot.py284. It did not reach the Shift click for that range or later native batch qualification. No recorded geometry snapshot establishes which half of the assertion failed. This source counterexample is not proof of the sole runtime cause.

Original one restoration passed0/.207032571s. Exact1467-node floor/953 ZIP assets/full69 RAW origins/1883 unchanged other66/protected266/bootstrap2/PREFIX matched. Fresh197-process privileged census found no private references or gaps. All10 recorded identities are absent. Whole return retained97 raw references,52 authored files and two journals, and explicitly returned private READ/EXEC to Bohr and Sch for independent closure:

/home/ts/wt/toad-sidebar-selected-targets-20261006/.artifacts/selected-target-installed-20261006/485-batch08-installed-purpose/whole-handback.json
SHA0079ee7446288d9ce195c70c87d0aa2178fe901d86d2b33760b00b538e98a80d /29024B.

## Remaining acceptance

No test, build, package/prefix import or App rerun accompanies this source change. Retained Coreb55/Toad713113/Textuala59 stay selected; this changes test operands only. Fresh affected installed acceptance uses this fixed helper root, actual returned holder/floor/origins/census/restore assessment, new exclusive outputs and new same-purpose authority. Previous Batch08 files, journals, corrected handoff and immutable authorities stay unchanged. Configured334's borrowed fixed helper root remains unchanged.
