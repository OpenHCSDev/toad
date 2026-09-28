# Rendered relationship removal before re-add

The integration pilot waited for an empty domain model then immediately re-added a relationship, while asynchronous row removal could still be pending. It could capture the obsolete row and incorrectly blame the following add for replacing an unchanged row. Wait for both model and rendered-row removal before re-adding. Keep the subsequent row-identity assertion unchanged.

Parent PR169 combined89 source tests and current mounted real tools/sidebar pilot pass. Pin core169 (06bef1a); current Textual pin remains4fa6a9c. This changes the fixture and dependency pin, not product UI behavior. CI deferred.
