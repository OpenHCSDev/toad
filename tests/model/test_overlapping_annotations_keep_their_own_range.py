"""Two annotations starting at the same offset stay two answers, each restoring its own range, also after one is corrected."""


from support.overlapping_annotations import overlapping_annotations


def test_overlapping_annotation_addresses_restore_their_own_range(tmp_path):
    found = overlapping_annotations(tmp_path)
    spans, labels, inspection, short, long = found.spans, found.labels, found.inspection, found.short, found.long
    assert all(found.observed.contains_span(span) for span in spans)
    assert spans[0].coordinates.offset == spans[1].coordinates.offset
    assert spans[0].coordinates.length != spans[1].coordinates.length
    ((_, (source,), _),) = inspection.working_memory()
    assert short.key != long.key
    assert short.annotation.span == spans[0] and long.annotation.span == spans[1]
    assert source.reader_path(short.key)[-1] == short
    assert source.reader_path(long.key)[-1] == long
    answers = tuple(answer for _, sources, _ in found.refined_groups
                    for current_source in sources for answer in current_source.children())
    corrected_short = next(answer for answer in answers if answer.annotation is found.corrected)
    retained_long = next(answer for answer in answers if answer.annotation is labels[1])
    assert corrected_short.key == short.key and retained_long.key == long.key
    assert found.corrected.working_memory_section == "Obeys"
